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

# CLO API 사용 여부: CLO Python Editor 안에서 실행하면 True 권장
LOAD_SAMPLES_INTO_CLO = True

# AddFabric 후 CLO export까지 다시 수행할지 여부.
# 보통 False 권장. 직접 패치한 zfab 자체가 결과물이므로 ExportZFab 실패 가능성을 피한다.
EXPORT_THROUGH_CLO_AFTER_LOAD = False

# UI에서 Warp/Weft가 뒤집혀 보이면 두 리스트를 서로 바꿔라.
WARP_FIELDS = ["fBuK", "fBuK_v2"]  # Bending-Warp 후보
WEFT_FIELDS = ["fBvK", "fBvK_v2"]  # Bending-Weft 후보

# 추가로 같이 패치하고 싶으면 True.
# 보통 Bending-Warp/Weft만 원하면 False 유지.
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


def make_ui_samples(n: int) -> List[float]:
    if n <= 1:
        return [0.0]
    vals = []
    for i in range(n):
        vals.append(100.0 * i / (n - 1))
    # 끝점 안정화
    vals[0] = 0.0
    vals[-1] = 100.0
    return vals


def make_sample_pairs(n: int, mode: str) -> List[Tuple[float, float]]:
    vals = make_ui_samples(n)
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
        # fBuK_v2 같은 longer key prefix 매칭 방지
        if val_off < len(data) and _is_identifier_byte(data[val_off]):
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


def patch_fab_bytes(data: bytes, warp_actual: float, weft_actual: float) -> Tuple[bytes, Dict[str, Any]]:
    buf = bytearray(data)

    patch_targets: List[Tuple[str, str, float]] = []
    for f in WARP_FIELDS:
        patch_targets.append(("warp", f, warp_actual))
    for f in WEFT_FIELDS:
        patch_targets.append(("weft", f, weft_actual))

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


def patch_zfab(input_zfab: str, output_zfab: str, warp_actual: float, weft_actual: float) -> Dict[str, Any]:
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
                before_scan = scan_fields_in_fab(data, sorted(set(WARP_FIELDS + WEFT_FIELDS + BUCKLING_WARP_FIELDS + BUCKLING_WEFT_FIELDS)))
                out_data, patch_info = patch_fab_bytes(data, warp_actual, weft_actual)
                after_scan = scan_fields_in_fab(out_data, sorted(set(WARP_FIELDS + WEFT_FIELDS + BUCKLING_WARP_FIELDS + BUCKLING_WEFT_FIELDS)))
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
                "logs": all_logs,
            }, f, indent=2, ensure_ascii=False)
        raise RuntimeError(f"No Bending-Warp/Weft value was patched. Check: {debug_path}")

    return {
        "input_zfab": input_zfab,
        "output_zfab": output_zfab,
        "fab_files": fab_files,
        "total_patched": total_patched,
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


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create bending-varied .zfab samples.")
    parser.add_argument("input_zfab", nargs="?", help="Base .zfab path.")
    parser.add_argument("out_dir", nargs="?", help="Output directory for sampled .zfab files.")
    parser.add_argument("--config", default="", help="Pipeline JSON config path.")
    parser.add_argument("--sample_count", type=int, default=None, help="Number of UI samples.")
    parser.add_argument("--sample_mode", default="", choices=["", "paired", "grid"], help="Sampling mode.")
    args, _ = parser.parse_known_args(argv)
    return args


def main(argv: List[str] = None):
    global WARP_FIELDS, WEFT_FIELDS, PATCH_BUCKLING_STIFFNESS
    global BUCKLING_WARP_FIELDS, BUCKLING_WEFT_FIELDS

    args = parse_args(sys.argv[1:] if argv is None else argv)
    default_config = os.path.join(os.path.dirname(SCRIPT_FILE), "dataset_pipeline_config.json")
    config_path = CONFIG_JSON_PATH or args.config or os.environ.get("CLO_DATASET_CONFIG", "")
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

    input_zfab = (
        args.input_zfab
        or deep_get(config, ["inputs", "base_fabric_zfab"])
        or deep_get(config, ["stage_1_fabric_sampler", "inputs", "base_zfab"])
        or deep_get(config, ["sampler", "input_zfab"])
        or deep_get(config, ["paths", "base_zfab"])
        or find_input_file(output_root, "zfab", "base zfab")
        or INPUT_ZFAB
    )
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

    if not input_zfab:
        raise RuntimeError("input_zfab is empty. Set inputs.base_fabric_zfab in the config, or pass input_zfab.")

    input_zfab = os.path.abspath(input_zfab)
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    debug_dir = os.path.abspath(debug_dir_config) if debug_dir_config else os.path.join(out_dir, "debug")
    os.makedirs(debug_dir, exist_ok=True)

    if not os.path.exists(input_zfab):
        raise RuntimeError(f"INPUT_ZFAB does not exist: {input_zfab}")

    pairs = make_sample_pairs(sample_count, sample_mode)
    summary: Dict[str, Any] = {
        "input_zfab": input_zfab,
        "out_dir": out_dir,
        "sample_count": sample_count,
        "sample_mode": sample_mode,
        "rule_text": RULE_TEXT,
        "rule_interpretation": "piecewise linear slope; UI=100 is clamped to actual=2000000",
        "warp_fields": WARP_FIELDS,
        "weft_fields": WEFT_FIELDS,
        "patch_buckling_stiffness": PATCH_BUCKLING_STIFFNESS,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "samples": [],
    }

    print("=" * 80)
    print("[Start] CLO ZFAB bending sampler")
    print("INPUT_ZFAB:", input_zfab)
    print("OUT_DIR   :", out_dir)
    print("MODE      :", sample_mode)
    print("SAMPLES   :", len(pairs))
    print("=" * 80)

    for idx, (ui_warp, ui_weft) in enumerate(pairs):
        warp_actual = ui_to_actual(ui_warp)
        weft_actual = ui_to_actual(ui_weft)

        stem = f"base_{idx:03d}"
        format_values = {
            "index": idx,
            "index1": idx + 1,
            "stem": stem,
            "warp_name": safe_name(ui_warp),
            "weft_name": safe_name(ui_weft),
            "ui_warp": ui_warp,
            "ui_weft": ui_weft,
        }
        out_zfab = os.path.join(
            out_dir,
            format_stage_file_name(zfab_name_template, **format_values),
        )
        out_json = os.path.join(
            out_dir,
            format_stage_file_name(json_name_template, **format_values),
        )

        print("\n" + "-" * 80)
        print(f"[Sample {idx+1}/{len(pairs)}] warp_ui={ui_warp:.4f}, weft_ui={ui_weft:.4f}")
        print(f"actual: warp={warp_actual}, weft={weft_actual}")

        patch_result = patch_zfab(input_zfab, out_zfab, warp_actual, weft_actual)

        clo_load_result = None
        clo_export_result = None
        if load_samples_into_clo:
            clo_load_result = load_into_clo_with_api(out_zfab)
            print("CLO AddFabric:", clo_load_result)

            if export_through_clo_after_load and clo_load_result.get("ok"):
                export_path = os.path.join(out_dir, stem + "_clo_exported.zfab")
                clo_export_result = export_through_clo_api(export_path, clo_load_result.get("added_fabric_index"))
                print("CLO ExportZFab:", clo_export_result)

        material = {
            "source_zfab": input_zfab,
            "output_zfab": out_zfab,
            "ui": {
                "bending_warp": ui_warp,
                "bending_weft": ui_weft,
            },
            "actual": {
                "bending_warp": warp_actual,
                "bending_weft": weft_actual,
            },
            "rule_text": RULE_TEXT,
            "rule_interpretation": summary["rule_interpretation"],
            "internal_fields": {
                "warp_fields": WARP_FIELDS,
                "weft_fields": WEFT_FIELDS,
            },
            "patch_result": patch_result,
            "clo_api": {
                "load_result": clo_load_result,
                "export_result": clo_export_result,
            },
        }
        write_json(out_json, material)

        summary["samples"].append({
            "index": idx,
            "ui_warp": ui_warp,
            "ui_weft": ui_weft,
            "actual_warp": warp_actual,
            "actual_weft": weft_actual,
            "zfab": out_zfab,
            "json": out_json,
            "output_files": {
                "zfab": out_zfab,
                "material_json": out_json,
            },
            "patched_count": patch_result["total_patched"],
            "clo_api_load": clo_load_result,
        })

    summary_path = os.path.abspath(summary_path_config) if summary_path_config else os.path.join(out_dir, "summary_bending_sampling.json")
    summary["output_files"] = {
        "fabric_dir": out_dir,
        "summary_json": summary_path,
        "debug_dir": debug_dir,
    }
    write_json(summary_path, summary)

    # Save a debug scan of target field positions/values in the source zfab.
    try:
        with zipfile.ZipFile(input_zfab, "r") as z:
            scans = {}
            for info in z.infolist():
                if info.filename.lower().endswith(".fab"):
                    data = z.read(info.filename)
                    scans[info.filename] = scan_fields_in_fab(data, sorted(set(WARP_FIELDS + WEFT_FIELDS + BUCKLING_WARP_FIELDS + BUCKLING_WEFT_FIELDS)))
            write_json(os.path.join(debug_dir, "base_zfab_field_scan.json"), scans)
    except Exception as e:
        write_json(os.path.join(debug_dir, "base_zfab_field_scan_error.json"), {"error": repr(e)})

    print("\n" + "=" * 80)
    print("[Finished]")
    print("OUT_DIR :", out_dir)
    print("SUMMARY :", summary_path)
    print("=" * 80)


if __name__ == "__main__":
    main()
