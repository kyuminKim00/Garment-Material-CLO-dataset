# -*- coding: utf-8 -*-


import os
import re
import sys
import json
import math
import time
import shutil
import struct
import zipfile
import argparse
import glob
import random
from pathlib import Path
from typing import Dict, List, Tuple, Any

# =============================================================================
# 사용자 설정
# =============================================================================

FALLBACK_SCRIPT_FILE = r"C:\Users\CGnA\Desktop\CLO\scripts\clo_fab_sampler.py"
SCRIPT_FILE = globals().get("__file__", FALLBACK_SCRIPT_FILE)
if not SCRIPT_FILE or str(SCRIPT_FILE).startswith("<") or not os.path.exists(SCRIPT_FILE):
    SCRIPT_FILE = FALLBACK_SCRIPT_FILE
SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(SCRIPT_FILE), ".."))
CONFIG_JSON_PATH = r"C:\Users\CGnA\Desktop\CLO\dataset_config.json"
INPUT_ZFAB = ""
OUT_DIR = os.path.join(SCRIPT_DIR, "bending_zfab_samples")

SAMPLE_COUNT = 10
SAMPLE_MODE = "paired"      # "paired" or "grid"
SAMPLE_DISTRIBUTION = "ui_uniform"  # "ui_uniform", "effective_ui_jittered", or "ui_bucket_jittered"
SAMPLE_SEED = 0
EFFECTIVE_UI_MIN = 55.0
EFFECTIVE_UI_CURVE = 1.0
UI_SAMPLE_BINS = [
    {"min": 0.0, "max": 20.0, "count": 1},
    {"min": 20.0, "max": 50.0, "count": 2},
    {"min": 50.0, "max": 70.0, "count": 2},
    {"min": 70.0, "max": 100.0, "count": 3},
]
PRESERVE_BENDING_V2_RATIO = False

# CLO API 사용 여부: CLO Python Editor 안에서 실행하면 True 권장
LOAD_SAMPLES_INTO_CLO = True

# AddFabric 후 CLO export까지 다시 수행할지 여부.
# 보통 False 권장. 직접 패치한 zfab 자체가 결과물이므로 ExportZFab 실패 가능성을 피한다.
EXPORT_THROUGH_CLO_AFTER_LOAD = False

# UI에서 Warp/Weft가 뒤집혀 보이면 두 리스트를 서로 바꿔라.
WARP_FIELDS = ["fBuK", "fBuK_v2"]  # Bending-Warp 후보
WEFT_FIELDS = ["fBvK", "fBvK_v2"]  # Bending-Weft 후보

# 하나의 bending stiffness level로 볼 때 Bias도 Warp/Weft와 같이 패치한다.
# CLO UI의 Bias 값은 shear-direction bending field도 함께 보는 케이스가 있다.
BIAS_FIELDS = [
    "fBhK",
    "fBhK_v2",
    "fBLeftShearK",
    "fBLeftShearK_v2",
    "fBRightShearK",
    "fBRightShearK_v2",
]
PATCH_BENDING_BIAS = True
V2_PRIMARY_FIELD_ALIASES = {
    "fBRightShearK_v2": "fBhK",
}

# Buckling stiffness는 bending stiffness와 다른 항목이라 기본적으로 유지한다.
PATCH_BUCKLING_STIFFNESS = False
BUCKLING_WARP_FIELDS = ["fBucklingStiffnessU"]
BUCKLING_WEFT_FIELDS = ["fBucklingStiffnessV"]

# =============================================================================
# UI -> actual 변환 규칙
# =============================================================================

RULE_TEXT = [
    "0~10: +10",
    "10~27: +50",
    "27~50: +100",
    "50~65: +1000",
    "65~83: +10000",
    "83~97: +100000",
    "98~99: +150000",
    "100: 2000000",
]

# 구간별 slope로 해석한다.
# 83~97, 98~99 사이의 97~98 공백은 실사용 샘플에서 거의 문제 없지만,
# 연속성을 위해 83~98을 +100000 구간으로 처리한다.
PIECEWISE_SEGMENTS = [
    (0.0, 10.0, 10.0),
    (10.0, 27.0, 50.0),
    (27.0, 50.0, 100.0),
    (50.0, 65.0, 1000.0),
    (65.0, 83.0, 10000.0),
    (83.0, 98.0, 100000.0),
    (98.0, 100.0, 150000.0),
]


def ui_to_actual(ui_value: float) -> float:
    """CLO UI 0~100 값을 내부 actual float 값으로 변환."""
    x = float(ui_value)
    if x <= 0.0:
        return 0.0
    if x >= 100.0:
        return 2000000.0

    total = 0.0
    for lo, hi, slope in PIECEWISE_SEGMENTS:
        if x <= lo:
            break
        dx = min(x, hi) - lo
        if dx > 0:
            total += dx * slope
        if x <= hi:
            break
    return float(total)


def make_ui_uniform_samples(n: int) -> List[float]:
    if n <= 1:
        return [0.0]
    vals = []
    for i in range(n):
        vals.append(100.0 * i / (n - 1))
    # 끝점 안정화
    vals[0] = 0.0
    vals[-1] = 100.0
    return vals


def make_effective_ui_jittered_samples(
    n: int,
    seed: int = 0,
    effective_min: float = 50.0,
    curve: float = 0.75,
) -> List[float]:
    """
    Sample UI values where bending differences are visually meaningful.

    The endpoints 0 and 100 are kept as anchors. Interior samples are drawn
    continuously inside stratified bins over [effective_min, 100], with a
    curve < 1.0 putting a little more resolution near high stiffness.
    This avoids repeatedly producing fixed class-like UI values.
    """
    if n <= 1:
        return [0.0]
    if n == 2:
        return [0.0, 100.0]

    effective_min = max(0.0, min(99.999, float(effective_min)))
    curve = max(0.05, float(curve))
    rng = random.Random(int(seed))
    interior_count = n - 2
    vals = [0.0]

    for i in range(interior_count):
        t = (i + rng.random()) / interior_count
        shaped = t ** curve
        vals.append(effective_min + (100.0 - effective_min) * shaped)

    vals.append(100.0)
    vals = sorted(round(v, 4) for v in vals)
    vals[0] = 0.0
    vals[-1] = 100.0
    return vals


def allocate_bucket_counts(bins: List[Dict[str, Any]], total_count: int, anchor_count: int) -> List[int]:
    interior_count = max(0, int(total_count) - int(anchor_count))
    if not bins:
        return []

    weights = [max(0.0, float(item.get("count", item.get("n", item.get("weight", 1.0))))) for item in bins]
    if sum(weights) <= 0.0:
        weights = [1.0 for _ in bins]

    active_indexes = [i for i, weight in enumerate(weights) if weight > 0.0]
    counts = [0 for _ in bins]
    if interior_count >= len(active_indexes):
        for i in active_indexes:
            counts[i] = 1
        interior_count -= len(active_indexes)

    total_weight = sum(weights)
    raw = [interior_count * weight / total_weight for weight in weights]
    extra_counts = [int(math.floor(value)) for value in raw]
    remaining = interior_count - sum(extra_counts)

    order = sorted(range(len(raw)), key=lambda i: (raw[i] - extra_counts[i], weights[i]), reverse=True)
    for i in order[:remaining]:
        extra_counts[i] += 1
    counts = [count + extra for count, extra in zip(counts, extra_counts)]
    return counts


def make_ui_bucket_jittered_samples(
    bins: List[Dict[str, Any]],
    seed: int = 0,
    total_count: int = None,
    include_min_anchor: bool = True,
    include_max_anchor: bool = True,
) -> List[float]:
    """
    Draw continuous random UI samples from configured UI ranges.

    Each range is internally stratified before jittering so samples cover the
    whole interval without collapsing into fixed class centers.
    """
    rng = random.Random(int(seed))
    if total_count is not None and total_count <= 1:
        return [0.0]

    anchor_count = int(bool(include_min_anchor)) + int(bool(include_max_anchor))
    bucket_counts = (
        allocate_bucket_counts(bins or [], total_count, anchor_count)
        if total_count is not None
        else [int(item.get("count", item.get("n", 0))) for item in (bins or [])]
    )

    vals: List[float] = []
    if include_min_anchor:
        vals.append(0.0)

    for item, count in zip(bins or [], bucket_counts):
        lo = float(item.get("min", item.get("lo", 0.0)))
        hi = float(item.get("max", item.get("hi", 100.0)))
        if count <= 0:
            continue
        lo = max(0.0, min(100.0, lo))
        hi = max(0.0, min(100.0, hi))
        if hi < lo:
            lo, hi = hi, lo
        if hi == lo:
            vals.extend([lo] * count)
            continue

        width = hi - lo
        for i in range(count):
            t = (i + rng.random()) / count
            vals.append(lo + width * t)

    if include_max_anchor:
        vals.append(100.0)

    # Keep exact anchors, but avoid duplicate random values landing exactly on them.
    vals = [max(0.0, min(100.0, float(v))) for v in vals]
    vals = sorted(round(v, 4) for v in vals)
    if include_min_anchor:
        vals[0] = 0.0
    if include_max_anchor:
        vals[-1] = 100.0
    return vals


def make_ui_samples(
    n: int,
    distribution: str = "ui_uniform",
    seed: int = 0,
    effective_min: float = 50.0,
    curve: float = 0.75,
    bins: List[Dict[str, Any]] = None,
) -> List[float]:
    dist = (distribution or "ui_uniform").lower()
    if dist in ("ui_uniform", "uniform"):
        return make_ui_uniform_samples(n)
    if dist in ("effective_ui_jittered", "effective", "jittered"):
        return make_effective_ui_jittered_samples(n, seed, effective_min, curve)
    if dist in ("ui_bucket_jittered", "bucket_jittered", "bucket"):
        return make_ui_bucket_jittered_samples(bins or UI_SAMPLE_BINS, seed, n)
    raise ValueError('sample_distribution must be "ui_uniform", "effective_ui_jittered", or "ui_bucket_jittered"')


def make_sample_pairs(
    n: int,
    mode: str,
    distribution: str = "ui_uniform",
    seed: int = 0,
    effective_min: float = 50.0,
    curve: float = 0.75,
    bins: List[Dict[str, Any]] = None,
) -> List[Tuple[float, float]]:
    vals = make_ui_samples(n, distribution, seed, effective_min, curve, bins)
    if mode.lower() == "paired":
        return [(v, v) for v in vals]
    if mode.lower() == "grid":
        return [(u, v) for u in vals for v in vals]
    raise ValueError('SAMPLE_MODE must be "paired" or "grid"')

# =============================================================================
# binary patch utilities
# =============================================================================

_IDENTIFIER = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def _is_identifier_byte(b: int) -> bool:
    return b in _IDENTIFIER


def find_exact_key_offsets(data: bytes, key: str) -> List[int]:
    """
    key 문자열 바로 뒤에 4-byte little-endian float가 오는 위치만 찾는다.
    예: fBuK가 fBuK_v2 안에서 잘못 매칭되는 것을 방지한다.
    반환값은 float payload 시작 offset 리스트.
    """
    key_b = key.encode("ascii")
    offsets = []
    start = 0
    while True:
        idx = data.find(key_b, start)
        if idx < 0:
            break
        val_off = idx + len(key_b)
        start = idx + 1
        if val_off + 4 > len(data):
            continue
        # Avoid matching fBuK inside fBuK_v2. The first byte of the float
        # payload can also be an ASCII identifier byte, so only skip the
        # known longer-key suffix form.
        if data[val_off:val_off + 3] == b"_v2":
            continue
        offsets.append(val_off)
    return offsets


def read_float_le(data: bytes, offset: int) -> float:
    return struct.unpack("<f", data[offset:offset + 4])[0]


def write_float_le(buf: bytearray, offset: int, value: float) -> None:
    buf[offset:offset + 4] = struct.pack("<f", float(value))


def scan_fields_in_fab(data: bytes, field_names: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {}
    for name in field_names:
        arr = []
        for off in find_exact_key_offsets(data, name):
            arr.append({
                "value_offset": off,
                "value_float_le": read_float_le(data, off),
                "raw_hex": data[off:off + 4].hex(),
            })
        result[name] = arr
    return result


def _first_field_value(data: bytes, field: str) -> Any:
    offsets = find_exact_key_offsets(data, field)
    if not offsets:
        return None
    return read_float_le(data, offsets[0])


def _safe_ratio(numerator: Any, denominator: Any, default: float = 1.0) -> float:
    try:
        numerator = float(numerator)
        denominator = float(denominator)
        if abs(denominator) < 1.0e-12:
            return default
        ratio = numerator / denominator
        if not math.isfinite(ratio) or ratio <= 0.0:
            return default
        return ratio
    except Exception:
        return default


def _primary_field_for_v2(field: str) -> str:
    if field in V2_PRIMARY_FIELD_ALIASES:
        return V2_PRIMARY_FIELD_ALIASES[field]
    if field.endswith("_v2"):
        return field[:-3]
    return field


def _field_ratio_for_v2(data: bytes, field: str, default: float = 1.0) -> float:
    if not field.endswith("_v2"):
        return default
    primary_field = _primary_field_for_v2(field)
    return _safe_ratio(_first_field_value(data, field), _first_field_value(data, primary_field), default)


def _scaled_field_value(data: bytes, field: str, actual_value: float, preserve_v2_ratio: bool) -> float:
    value = float(actual_value)
    if preserve_v2_ratio and field.endswith("_v2"):
        value *= _field_ratio_for_v2(data, field)
    return value


def patch_fab_bytes(
    data: bytes,
    warp_actual: float,
    weft_actual: float,
    bias_actual: float = None,
    preserve_bending_v2_ratio: bool = False,
) -> Tuple[bytes, Dict[str, Any]]:
    buf = bytearray(data)

    if bias_actual is None:
        bias_actual = (float(warp_actual) + float(weft_actual)) * 0.5

    patch_targets: List[Tuple[str, str, float]] = []
    for f in WARP_FIELDS:
        patch_targets.append(("warp", f, _scaled_field_value(data, f, warp_actual, preserve_bending_v2_ratio)))
    for f in WEFT_FIELDS:
        patch_targets.append(("weft", f, _scaled_field_value(data, f, weft_actual, preserve_bending_v2_ratio)))
    if PATCH_BENDING_BIAS:
        for f in BIAS_FIELDS:
            patch_targets.append(("bias", f, _scaled_field_value(data, f, bias_actual, preserve_bending_v2_ratio)))

    if PATCH_BUCKLING_STIFFNESS:
        for f in BUCKLING_WARP_FIELDS:
            patch_targets.append(("warp_buckling", f, warp_actual))
        for f in BUCKLING_WEFT_FIELDS:
            patch_targets.append(("weft_buckling", f, weft_actual))

    patch_log: List[Dict[str, Any]] = []
    patched_count = 0

    for role, field, value in patch_targets:
        offsets = find_exact_key_offsets(data, field)
        for off in offsets:
            old_val = read_float_le(data, off)
            write_float_le(buf, off, value)
            new_val = read_float_le(bytes(buf), off)
            patch_log.append({
                "role": role,
                "field": field,
                "value_offset": off,
                "old_value": old_val,
                "new_value": new_val,
                "old_hex": data[off:off + 4].hex(),
                "new_hex": bytes(buf)[off:off + 4].hex(),
            })
            patched_count += 1

    info = {
        "patched_count": patched_count,
        "preserve_bending_v2_ratio": preserve_bending_v2_ratio,
        "bending_v2_ratios": {
            "warp": {f: _field_ratio_for_v2(data, f) for f in WARP_FIELDS if f.endswith("_v2")},
            "weft": {f: _field_ratio_for_v2(data, f) for f in WEFT_FIELDS if f.endswith("_v2")},
            "bias": {f: _field_ratio_for_v2(data, f) for f in BIAS_FIELDS if f.endswith("_v2")},
        },
        "patch_log": patch_log,
    }
    return bytes(buf), info


def copy_zipinfo(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(info.filename, info.date_time)
    zi.comment = info.comment
    zi.extra = info.extra
    zi.internal_attr = info.internal_attr
    zi.external_attr = info.external_attr
    zi.create_system = info.create_system
    zi.compress_type = info.compress_type
    return zi


def patch_zfab(
    input_zfab: str,
    output_zfab: str,
    warp_actual: float,
    weft_actual: float,
    bias_actual: float = None,
    preserve_bending_v2_ratio: bool = False,
) -> Dict[str, Any]:
    if not zipfile.is_zipfile(input_zfab):
        raise RuntimeError(f"Input is not a valid .zfab zip: {input_zfab}")

    os.makedirs(os.path.dirname(output_zfab), exist_ok=True)

    all_logs: List[Dict[str, Any]] = []
    fab_files = []
    total_patched = 0

    with zipfile.ZipFile(input_zfab, "r") as zin, zipfile.ZipFile(output_zfab, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            out_data = data

            if info.filename.lower().endswith(".fab"):
                fab_files.append(info.filename)
                scan_fields = sorted(set(WARP_FIELDS + WEFT_FIELDS + BIAS_FIELDS + BUCKLING_WARP_FIELDS + BUCKLING_WEFT_FIELDS))
                before_scan = scan_fields_in_fab(data, scan_fields)
                out_data, patch_info = patch_fab_bytes(data, warp_actual, weft_actual, bias_actual, preserve_bending_v2_ratio)
                after_scan = scan_fields_in_fab(out_data, scan_fields)
                total_patched += patch_info["patched_count"]
                all_logs.append({
                    "fab_file": info.filename,
                    "before_scan": before_scan,
                    "after_scan": after_scan,
                    "patched_count": patch_info["patched_count"],
                    "patch_log": patch_info["patch_log"],
                })

            zout.writestr(copy_zipinfo(info), out_data)

    if not fab_files:
        raise RuntimeError("No .fab file found inside zfab.")
    if total_patched == 0:
        debug_path = os.path.join(os.path.dirname(output_zfab), "debug_no_patch.json")
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump({
                "input_zfab": input_zfab,
                "fab_files": fab_files,
                "warp_fields": WARP_FIELDS,
                "weft_fields": WEFT_FIELDS,
                "bias_fields": BIAS_FIELDS,
                "patch_bending_bias": PATCH_BENDING_BIAS,
                "logs": all_logs,
            }, f, indent=2, ensure_ascii=False)
        raise RuntimeError(f"No Bending-Warp/Weft value was patched. Check: {debug_path}")

    return {
        "input_zfab": input_zfab,
        "output_zfab": output_zfab,
        "fab_files": fab_files,
        "total_patched": total_patched,
        "preserve_bending_v2_ratio": preserve_bending_v2_ratio,
        "logs": all_logs,
    }

# =============================================================================
# CLO API utilities
# =============================================================================


def get_fabric_api():
    """CLO Python Editor에서는 fabric_api가 global로 존재할 수 있다."""
    g = globals()
    if "fabric_api" in g:
        return g["fabric_api"]

    # 일부 환경에서 모듈 형태로 노출될 가능성 대응
    for mod_name in ("fabric_api", "CLOAPIInterface"):
        try:
            mod = __import__(mod_name)
            if mod_name == "fabric_api":
                return mod
            if hasattr(mod, "fabric_api"):
                return getattr(mod, "fabric_api")
        except Exception:
            pass
    return None


def load_into_clo_with_api(zfab_path: str) -> Dict[str, Any]:
    api = get_fabric_api()
    if api is None:
        return {"used": False, "ok": False, "reason": "fabric_api not found. Run inside CLO Python Editor to use CLO API."}

    try:
        idx = api.AddFabric(zfab_path)
        return {"used": True, "ok": True, "added_fabric_index": idx}
    except Exception as e:
        return {"used": True, "ok": False, "reason": repr(e)}


def export_through_clo_api(output_path: str, fabric_index: Any = None) -> Dict[str, Any]:
    api = get_fabric_api()
    if api is None:
        return {"used": False, "ok": False, "reason": "fabric_api not found"}
    try:
        if fabric_index is not None and isinstance(fabric_index, int):
            ret = api.ExportZFab(output_path, fabric_index)
        else:
            ret = api.ExportZFab(output_path)
        return {"used": True, "ok": bool(ret), "returned_path": ret}
    except Exception as e:
        # ExportFabric fallback
        try:
            if fabric_index is not None and isinstance(fabric_index, int):
                ret = api.ExportFabric(output_path, fabric_index)
            else:
                ret = api.ExportFabric(output_path)
            return {"used": True, "ok": bool(ret), "returned_path": ret, "fallback": "ExportFabric"}
        except Exception as e2:
            return {"used": True, "ok": False, "reason": repr(e), "fallback_reason": repr(e2)}

# =============================================================================
# main
# =============================================================================


def safe_name(v: float) -> str:
    return (f"{v:06.2f}").replace(".", "p")


def safe_id(value: Any, fallback: str = "item") -> str:
    text = str(value or fallback).strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = text.strip("._-")
    return text or fallback


def format_stage_file_name(template: str, **values: Any) -> str:
    try:
        return template.format(**values)
    except Exception:
        return template


def write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def deep_get(obj: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def load_config(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def resolve_config_path(path: Any, output_root: str = "") -> str:
    if path is None or str(path).strip() == "":
        return ""
    resolved = os.path.expanduser(str(path))
    if not os.path.isabs(resolved) and output_root:
        resolved = os.path.join(output_root, resolved)
    return os.path.abspath(resolved)


def find_input_file(root_dir: str, extension: str, label: str) -> str:
    if not root_dir:
        return ""
    pattern = os.path.join(root_dir, f"*.{extension.lstrip('.')}")
    candidates = [path for path in glob.glob(pattern) if os.path.isfile(path)]
    if not candidates:
        return ""
    ext = extension.lstrip(".").lower()

    def rank(path: str):
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        if stem == "base":
            score = 0
        elif stem == f"base_{ext}":
            score = 1
        elif "base_a_pose" in stem:
            score = 2
        elif stem.startswith("base"):
            score = 3
        else:
            score = 4
        return (score, len(stem), stem)

    return os.path.abspath(sorted(candidates, key=rank)[0])


def discover_input_files(root_dir: str, extension: str) -> List[str]:
    if not root_dir or not os.path.exists(root_dir):
        return []
    ext = extension.lstrip(".").lower()
    found: List[str] = []
    for dirpath, _, filenames in os.walk(root_dir):
        matches = sorted(
            os.path.join(dirpath, name)
            for name in filenames
            if name.lower().endswith("." + ext)
        )
        found.extend(matches)
    return [os.path.abspath(path) for path in sorted(found)]


def discover_fabric_inputs(config: Dict[str, Any], output_root: str, explicit_input_zfab: str) -> List[Dict[str, Any]]:
    entries = (
        deep_get(config, ["inputs", "fabrics"])
        or deep_get(config, ["stage_1_fabric_sampler", "inputs", "fabrics"])
        or []
    )
    fabrics: List[Dict[str, Any]] = []

    if isinstance(entries, list):
        for idx, entry in enumerate(entries):
            if isinstance(entry, str):
                path = entry
                fabric_id = safe_id(os.path.splitext(os.path.basename(path))[0], f"fabric_{idx:03d}")
                metadata = {}
            elif isinstance(entry, dict):
                path = entry.get("zfab") or entry.get("path") or entry.get("base_zfab") or ""
                fabric_id = safe_id(entry.get("id") or entry.get("name") or os.path.splitext(os.path.basename(path))[0], f"fabric_{idx:03d}")
                metadata = {k: v for k, v in entry.items() if k not in ("zfab", "path", "base_zfab")}
            else:
                continue
            if path:
                fabrics.append({
                    "fabric_id": fabric_id,
                    "zfab": resolve_config_path(path, output_root),
                    "metadata": metadata,
                })

    input_dir = (
        deep_get(config, ["inputs", "input_dir"])
        or deep_get(config, ["stage_1_fabric_sampler", "inputs", "input_dir"])
        or "input"
    )
    input_dir = resolve_config_path(input_dir, output_root)
    fabrics_dir = (
        deep_get(config, ["inputs", "fabrics_dir"])
        or deep_get(config, ["stage_1_fabric_sampler", "inputs", "fabrics_dir"])
        or os.path.join(input_dir, "fabrics")
    )
    if fabrics_dir:
        fabrics_dir = resolve_config_path(fabrics_dir, output_root)
        for path in discover_input_files(fabrics_dir, "zfab"):
            rel_parent = os.path.relpath(os.path.dirname(path), fabrics_dir)
            stem = os.path.splitext(os.path.basename(path))[0]
            fabric_id_source = stem if rel_parent == "." else rel_parent.replace(os.sep, "_")
            fabric_id = safe_id(fabric_id_source, f"fabric_{len(fabrics):03d}")
            fabrics.append({"fabric_id": fabric_id, "zfab": path, "metadata": {"source": "fabrics_dir"}})

    fallback_zfab = (
        explicit_input_zfab
        or deep_get(config, ["inputs", "base_fabric_zfab"])
        or deep_get(config, ["stage_1_fabric_sampler", "inputs", "base_zfab"])
        or deep_get(config, ["sampler", "input_zfab"])
        or deep_get(config, ["paths", "base_zfab"])
        or find_input_file(output_root, "zfab", "base zfab")
        or INPUT_ZFAB
    )
    if fallback_zfab and not fabrics:
        fabrics.append({
            "fabric_id": "fabric_000",
            "zfab": resolve_config_path(fallback_zfab, output_root),
            "metadata": {"source": "legacy_base_fabric_zfab"},
        })

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in fabrics:
        key = os.path.normcase(os.path.abspath(item["zfab"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create bending-varied .zfab samples.")
    parser.add_argument("input_zfab", nargs="?", help="Base .zfab path.")
    parser.add_argument("out_dir", nargs="?", help="Output directory for sampled .zfab files.")
    parser.add_argument("--config", default="", help="Pipeline JSON config path.")
    parser.add_argument("--sample_count", type=int, default=None, help="Number of UI samples.")
    parser.add_argument("--sample_mode", default="", choices=["", "paired", "grid"], help="Sampling mode.")
    parser.add_argument(
        "--sample_distribution",
        default="",
        choices=["", "ui_uniform", "effective_ui_jittered", "ui_bucket_jittered"],
        help="How to choose UI bending values.",
    )
    parser.add_argument("--sample_seed", type=int, default=None, help="Random seed for jittered sampling.")
    parser.add_argument("--effective_ui_min", type=float, default=None, help="Lower UI bound for effective jittered sampling.")
    parser.add_argument("--effective_ui_curve", type=float, default=None, help="Power curve for effective jittered sampling; <1 biases high.")
    parser.add_argument("--sample_bins_json", default="", help="JSON list of UI bins for ui_bucket_jittered sampling.")
    parser.add_argument(
        "--preserve_bending_v2_ratio",
        action="store_true",
        default=None,
        help="Scale *_v2 bending fields by the base fB*_v2/fB* ratio.",
    )
    parser.add_argument(
        "--no_preserve_bending_v2_ratio",
        action="store_false",
        dest="preserve_bending_v2_ratio",
        help="Patch *_v2 bending fields to the same raw value as the primary fields.",
    )
    args, _ = parser.parse_known_args(argv)
    return args


def main(argv: List[str] = None):
    global WARP_FIELDS, WEFT_FIELDS, BIAS_FIELDS, PATCH_BENDING_BIAS, PATCH_BUCKLING_STIFFNESS
    global BUCKLING_WARP_FIELDS, BUCKLING_WEFT_FIELDS

    args = parse_args(sys.argv[1:] if argv is None else argv)
    default_config = os.path.join(os.path.dirname(SCRIPT_FILE), "dataset_pipeline_config.json")
    config_path = args.config or os.environ.get("CLO_DATASET_CONFIG", "") or CONFIG_JSON_PATH
    if not config_path and os.path.exists(default_config):
        config_path = default_config
    config = load_config(config_path)
    output_root = (
        deep_get(config, ["project", "output_dir"])
        or deep_get(config, ["project", "dataset_root"])
        or deep_get(config, ["paths", "output_dir"])
        or deep_get(config, ["paths", "dataset_root"])
        or deep_get(config, ["paths", "root_dir"])
        or ""
    )
    output_root = os.path.abspath(os.path.expanduser(output_root)) if output_root else ""

    fabric_inputs = discover_fabric_inputs(config, output_root, args.input_zfab or "")
    out_dir = (
        args.out_dir
        or deep_get(config, ["stage_1_fabric_sampler", "outputs", "fabric_dir"])
        or deep_get(config, ["sampler", "output_dir"])
        or deep_get(config, ["paths", "zfab_output_dir"])
        or (os.path.join(output_root, deep_get(config, ["naming", "fabric_dir"], "01_fabric_bending")) if output_root else "")
        or (os.path.join(output_root, "bending_zfab_samples") if output_root else "")
        or OUT_DIR
    )
    debug_dir_config = deep_get(config, ["stage_1_fabric_sampler", "outputs", "debug_dir"], "")
    summary_path_config = deep_get(config, ["stage_1_fabric_sampler", "outputs", "summary_json"], "")
    variant_dir_template = str(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "outputs", "variant_dir_template"],
            deep_get(config, ["naming", "fabric_variant_dir_template"], ""),
        )
    )
    bend_dir_template = str(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "outputs", "bend_dir_template"],
            deep_get(config, ["naming", "bend_dir_template"], "bend_{index:03d}"),
        )
    )
    zfab_name_template = str(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "outputs", "zfab_name_template"],
            deep_get(config, ["naming", "fabric_file_template"], "base_{index:03d}.zfab"),
        )
    )
    json_name_template = str(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "outputs", "material_json_name_template"],
            deep_get(config, ["naming", "material_json_template"], "base_{index:03d}.material.json"),
        )
    )

    sample_count = int(
        args.sample_count
        if args.sample_count is not None
        else deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "sample_count"],
            deep_get(config, ["fabric_sampler", "sample_count"], deep_get(config, ["sampler", "sample_count"], SAMPLE_COUNT)),
        )
    )
    sample_mode = args.sample_mode or deep_get(
        config,
        ["stage_1_fabric_sampler", "settings", "sample_mode"],
        deep_get(config, ["fabric_sampler", "sample_mode"], deep_get(config, ["sampler", "sample_mode"], SAMPLE_MODE)),
    )
    sample_distribution = args.sample_distribution or deep_get(
        config,
        ["stage_1_fabric_sampler", "settings", "sample_distribution"],
        deep_get(
            config,
            ["fabric_sampler", "sample_distribution"],
            deep_get(config, ["sampler", "sample_distribution"], SAMPLE_DISTRIBUTION),
        ),
    )
    sample_seed = int(
        args.sample_seed
        if args.sample_seed is not None
        else deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "sample_seed"],
            deep_get(config, ["fabric_sampler", "sample_seed"], deep_get(config, ["sampler", "sample_seed"], SAMPLE_SEED)),
        )
    )
    effective_ui_min = float(
        args.effective_ui_min
        if args.effective_ui_min is not None
        else deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "effective_ui_min"],
            deep_get(config, ["fabric_sampler", "effective_ui_min"], deep_get(config, ["sampler", "effective_ui_min"], EFFECTIVE_UI_MIN)),
        )
    )
    effective_ui_curve = float(
        args.effective_ui_curve
        if args.effective_ui_curve is not None
        else deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "effective_ui_curve"],
            deep_get(config, ["fabric_sampler", "effective_ui_curve"], deep_get(config, ["sampler", "effective_ui_curve"], EFFECTIVE_UI_CURVE)),
        )
    )
    sample_bins = deep_get(
        config,
        ["stage_1_fabric_sampler", "settings", "sample_bins"],
        deep_get(config, ["fabric_sampler", "sample_bins"], deep_get(config, ["sampler", "sample_bins"], UI_SAMPLE_BINS)),
    )
    if args.sample_bins_json:
        sample_bins = json.loads(args.sample_bins_json)
    preserve_bending_v2_ratio = bool(
        args.preserve_bending_v2_ratio
        if args.preserve_bending_v2_ratio is not None
        else deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "preserve_bending_v2_ratio"],
            deep_get(
                config,
                ["fabric_sampler", "preserve_bending_v2_ratio"],
                deep_get(config, ["sampler", "preserve_bending_v2_ratio"], PRESERVE_BENDING_V2_RATIO),
            ),
        )
    )
    load_samples_into_clo = bool(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "load_samples_into_clo"],
            deep_get(config, ["fabric_sampler", "load_samples_into_clo"], deep_get(config, ["sampler", "load_samples_into_clo"], LOAD_SAMPLES_INTO_CLO)),
        )
    )
    export_through_clo_after_load = bool(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "export_through_clo_after_load"],
            deep_get(
                config,
                ["fabric_sampler", "export_through_clo_after_load"],
                deep_get(config, ["sampler", "export_through_clo_after_load"], EXPORT_THROUGH_CLO_AFTER_LOAD),
            ),
        )
    )

    WARP_FIELDS = list(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "warp_fields"],
            deep_get(config, ["fabric_sampler", "warp_fields"], deep_get(config, ["sampler", "warp_fields"], WARP_FIELDS)),
        )
    )
    WEFT_FIELDS = list(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "weft_fields"],
            deep_get(config, ["fabric_sampler", "weft_fields"], deep_get(config, ["sampler", "weft_fields"], WEFT_FIELDS)),
        )
    )
    BIAS_FIELDS = list(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "bias_fields"],
            deep_get(config, ["fabric_sampler", "bias_fields"], deep_get(config, ["sampler", "bias_fields"], BIAS_FIELDS)),
        )
    )
    PATCH_BENDING_BIAS = bool(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "patch_bending_bias"],
            deep_get(config, ["fabric_sampler", "patch_bending_bias"], deep_get(config, ["sampler", "patch_bending_bias"], PATCH_BENDING_BIAS)),
        )
    )
    PATCH_BUCKLING_STIFFNESS = bool(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "patch_buckling_stiffness"],
            deep_get(config, ["fabric_sampler", "patch_buckling_stiffness"], deep_get(config, ["sampler", "patch_buckling_stiffness"], PATCH_BUCKLING_STIFFNESS)),
        )
    )
    BUCKLING_WARP_FIELDS = list(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "buckling_warp_fields"],
            deep_get(config, ["fabric_sampler", "buckling_warp_fields"], deep_get(config, ["sampler", "buckling_warp_fields"], BUCKLING_WARP_FIELDS)),
        )
    )
    BUCKLING_WEFT_FIELDS = list(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "buckling_weft_fields"],
            deep_get(config, ["fabric_sampler", "buckling_weft_fields"], deep_get(config, ["sampler", "buckling_weft_fields"], BUCKLING_WEFT_FIELDS)),
        )
    )

    if not fabric_inputs:
        raise RuntimeError("No fabric input found. Put .zfab files under output_dir/input/fabrics, set inputs.fabrics_dir, or pass input_zfab.")

    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    debug_dir = os.path.abspath(debug_dir_config) if debug_dir_config else os.path.join(out_dir, "debug")
    os.makedirs(debug_dir, exist_ok=True)

    for fabric in fabric_inputs:
        if not os.path.exists(fabric["zfab"]):
            raise RuntimeError(f"Input fabric zfab does not exist: {fabric['zfab']}")

    if not variant_dir_template and len(fabric_inputs) > 1:
        variant_dir_template = "{fabric_id}/{bend_id}"

    pairs = make_sample_pairs(
        sample_count,
        sample_mode,
        sample_distribution,
        sample_seed,
        effective_ui_min,
        effective_ui_curve,
        sample_bins,
    )
    sample_bin_allocations = None
    if str(sample_distribution).lower() in ("ui_bucket_jittered", "bucket_jittered", "bucket"):
        sample_bin_allocations = allocate_bucket_counts(sample_bins or UI_SAMPLE_BINS, sample_count, 2)
    summary: Dict[str, Any] = {
        "fabric_inputs": fabric_inputs,
        "out_dir": out_dir,
        "requested_sample_count": sample_count,
        "bend_count_per_fabric": len(pairs),
        "sample_count": len(pairs) * len(fabric_inputs),
        "sample_mode": sample_mode,
        "sample_distribution": sample_distribution,
        "sample_seed": sample_seed,
        "effective_ui_min": effective_ui_min,
        "effective_ui_curve": effective_ui_curve,
        "sample_bins": sample_bins,
        "sample_bin_allocations": sample_bin_allocations,
        "variant_dir_template": variant_dir_template,
        "bend_dir_template": bend_dir_template,
        "preserve_bending_v2_ratio": preserve_bending_v2_ratio,
        "rule_text": RULE_TEXT,
        "rule_interpretation": "piecewise linear slope; UI=100 is clamped to actual=2000000",
        "warp_fields": WARP_FIELDS,
        "weft_fields": WEFT_FIELDS,
        "bias_fields": BIAS_FIELDS,
        "patch_bending_bias": PATCH_BENDING_BIAS,
        "patch_buckling_stiffness": PATCH_BUCKLING_STIFFNESS,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "samples": [],
    }

    print("=" * 80)
    print("[Start] CLO ZFAB bending sampler")
    print("FABRICS   :", len(fabric_inputs))
    print("OUT_DIR   :", out_dir)
    print("MODE      :", sample_mode)
    print("DIST      :", sample_distribution)
    print("SEED      :", sample_seed)
    print("V2 RATIO  :", preserve_bending_v2_ratio)
    print("REQUESTED :", sample_count)
    print("BENDS     :", len(pairs))
    print("SAMPLES   :", len(pairs) * len(fabric_inputs))
    print("=" * 80)

    sample_index = 0
    for fabric_idx, fabric in enumerate(fabric_inputs):
        fabric_id = safe_id(fabric["fabric_id"], f"fabric_{fabric_idx:03d}")
        input_zfab = fabric["zfab"]
        print("\n" + "=" * 80)
        print(f"[Fabric {fabric_idx+1}/{len(fabric_inputs)}] {fabric_id}")
        print("INPUT_ZFAB:", input_zfab)

        for bend_idx, (ui_warp, ui_weft) in enumerate(pairs):
            ui_bias = (float(ui_warp) + float(ui_weft)) * 0.5
            warp_actual = ui_to_actual(ui_warp)
            weft_actual = ui_to_actual(ui_weft)
            bias_actual = ui_to_actual(ui_bias)
            bend_id = safe_id(
                format_stage_file_name(
                    bend_dir_template,
                    index=bend_idx,
                    index1=bend_idx + 1,
                    ui_warp=ui_warp,
                    ui_weft=ui_weft,
                    warp_name=safe_name(ui_warp),
                    weft_name=safe_name(ui_weft),
                ),
                f"bend_{bend_idx:03d}",
            )
            sample_id = f"{fabric_id}__{bend_id}"
            stem = f"{fabric_id}_{bend_id}"
            format_values = {
                "index": bend_idx,
                "index1": bend_idx + 1,
                "sample_index": sample_index,
                "sample_index1": sample_index + 1,
                "fabric_index": fabric_idx,
                "fabric_index1": fabric_idx + 1,
                "bend_index": bend_idx,
                "bend_index1": bend_idx + 1,
                "fabric_id": fabric_id,
                "bend_id": bend_id,
                "sample_id": sample_id,
                "stem": stem,
                "warp_name": safe_name(ui_warp),
                "weft_name": safe_name(ui_weft),
                "ui_warp": ui_warp,
                "ui_weft": ui_weft,
            }
            variant_rel_dir = format_stage_file_name(variant_dir_template, **format_values) if variant_dir_template else ""
            variant_dir = os.path.join(out_dir, variant_rel_dir) if variant_rel_dir else out_dir
            out_zfab = os.path.join(variant_dir, format_stage_file_name(zfab_name_template, **format_values))
            out_json = os.path.join(variant_dir, format_stage_file_name(json_name_template, **format_values))

            print("\n" + "-" * 80)
            print(f"[Sample {sample_index+1}/{summary['sample_count']}] {sample_id}")
            print(f"warp_ui={ui_warp:.4f}, weft_ui={ui_weft:.4f}, bias_ui={ui_bias:.4f}")
            print(f"actual: warp={warp_actual}, weft={weft_actual}, bias={bias_actual}")

            patch_result = patch_zfab(input_zfab, out_zfab, warp_actual, weft_actual, bias_actual, preserve_bending_v2_ratio)

            clo_load_result = None
            clo_export_result = None
            if load_samples_into_clo:
                clo_load_result = load_into_clo_with_api(out_zfab)
                print("CLO AddFabric:", clo_load_result)

                if export_through_clo_after_load and clo_load_result.get("ok"):
                    export_path = os.path.join(variant_dir, stem + "_clo_exported.zfab")
                    clo_export_result = export_through_clo_api(export_path, clo_load_result.get("added_fabric_index"))
                    print("CLO ExportZFab:", clo_export_result)

            material = {
                "sample_id": sample_id,
                "fabric_id": fabric_id,
                "bend_id": bend_id,
                "fabric_index": fabric_idx,
                "bend_index": bend_idx,
                "source_zfab": input_zfab,
                "output_zfab": out_zfab,
                "ui": {
                    "bending_warp": ui_warp,
                    "bending_weft": ui_weft,
                    "bending_bias": ui_bias,
                },
                "actual": {
                    "bending_warp": warp_actual,
                    "bending_weft": weft_actual,
                    "bending_bias": bias_actual,
                },
                "rule_text": RULE_TEXT,
                "rule_interpretation": summary["rule_interpretation"],
                "preserve_bending_v2_ratio": preserve_bending_v2_ratio,
                "internal_fields": {
                    "warp_fields": WARP_FIELDS,
                    "weft_fields": WEFT_FIELDS,
                    "bias_fields": BIAS_FIELDS,
                    "patch_bending_bias": PATCH_BENDING_BIAS,
                },
                "patch_result": patch_result,
                "clo_api": {
                    "load_result": clo_load_result,
                    "export_result": clo_export_result,
                },
            }
            write_json(out_json, material)

            summary["samples"].append({
                "sample_index": sample_index,
                "fabric_index": fabric_idx,
                "bend_index": bend_idx,
                "sample_id": sample_id,
                "fabric_id": fabric_id,
                "bend_id": bend_id,
                "source_zfab": input_zfab,
                "ui_warp": ui_warp,
                "ui_weft": ui_weft,
                "ui_bias": ui_bias,
                "actual_warp": warp_actual,
                "actual_weft": weft_actual,
                "actual_bias": bias_actual,
                "zfab": out_zfab,
                "json": out_json,
                "output_files": {
                    "zfab": out_zfab,
                    "material_json": out_json,
                },
                "patched_count": patch_result["total_patched"],
                "clo_api_load": clo_load_result,
            })
            sample_index += 1

    summary_path = os.path.abspath(summary_path_config) if summary_path_config else os.path.join(out_dir, "summary_bending_sampling.json")
    summary["output_files"] = {
        "fabric_dir": out_dir,
        "summary_json": summary_path,
        "debug_dir": debug_dir,
    }
    write_json(summary_path, summary)

    # Save debug scans of target field positions/values in each source zfab.
    all_scans: Dict[str, Any] = {}
    for fabric in fabric_inputs:
        fabric_id = safe_id(fabric["fabric_id"], "fabric")
        input_zfab = fabric["zfab"]
        try:
            with zipfile.ZipFile(input_zfab, "r") as z:
                scans = {}
                for info in z.infolist():
                    if info.filename.lower().endswith(".fab"):
                        data = z.read(info.filename)
                        scans[info.filename] = scan_fields_in_fab(data, sorted(set(WARP_FIELDS + WEFT_FIELDS + BIAS_FIELDS + BUCKLING_WARP_FIELDS + BUCKLING_WEFT_FIELDS)))
                all_scans[fabric_id] = scans
                write_json(os.path.join(debug_dir, f"{fabric_id}_zfab_field_scan.json"), scans)
        except Exception as e:
            all_scans[fabric_id] = {"error": repr(e)}
            write_json(os.path.join(debug_dir, f"{fabric_id}_zfab_field_scan_error.json"), {"error": repr(e)})
    write_json(os.path.join(debug_dir, "all_zfab_field_scans.json"), all_scans)

    print("\n" + "=" * 80)
    print("[Finished]")
    print("OUT_DIR :", out_dir)
    print("SUMMARY :", summary_path)
    print("=" * 80)


if __name__ == "__main__":
    main()
