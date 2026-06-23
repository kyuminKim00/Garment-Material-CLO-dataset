# run_sim_render_for_zfab_samples.py
# Run inside CLO Python Script Editor
#
# 목적:
#   10개의 sample .zfab fabric을 바꿔가며
#   동일 garment/avatar A-pose에서 simulation 후 render 저장.
#
# 출력:
#   OUT_DIR/
#     sample_000/
#       images/
#       material.json
#       sim_result.zprj
#       summary.json
#     sample_001/
#       ...

import os
import json
import shutil
import time
import glob
import sys
import argparse
import importlib.util
import inspect
import hashlib
import struct
import zipfile

try:
    import import_api
    import export_api
    import fabric_api
    import pattern_api
    import utility_api
    CLO_API_IMPORT_ERROR = None
except Exception as e:
    import_api = None
    export_api = None
    fabric_api = None
    pattern_api = None
    utility_api = None
    CLO_API_IMPORT_ERROR = e


# =============================================================================
# Config
# =============================================================================

# A-pose avatar + garment가 들어있는 base project
# 매 sample마다 이걸 다시 열어서 초기 상태를 동일하게 맞춤.
CONFIG_JSON_PATH = r"C:\Users\CGnA\Desktop\CLO\dataset_config.json"
CONFIG_DIR = os.path.dirname(CONFIG_JSON_PATH)
SCRIPT_FILE = globals().get("__file__", "")
if not SCRIPT_FILE or str(SCRIPT_FILE).startswith("<") or not os.path.exists(SCRIPT_FILE):
    SCRIPT_FILE = os.path.join(CONFIG_DIR, "scripts", "01_clo_make_dataset.py")
SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(SCRIPT_FILE), ".."))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
CLO_EXPORT_OBJ_FILE = os.path.join(SCRIPT_DIR, "utils", "clo_export_obj.py")
try:
    clo_export_obj_spec = importlib.util.spec_from_file_location(
        "clo_export_obj_pipeline",
        CLO_EXPORT_OBJ_FILE,
    )
    if clo_export_obj_spec is None or clo_export_obj_spec.loader is None:
        raise RuntimeError(f"Could not load module spec: {CLO_EXPORT_OBJ_FILE}")
    clo_export_obj_module = importlib.util.module_from_spec(clo_export_obj_spec)
    clo_export_obj_spec.loader.exec_module(clo_export_obj_module)
    export_clo_obj = clo_export_obj_module.export_obj
    make_clo_obj_option = clo_export_obj_module.make_basic_option
    CLO_EXPORT_OBJ_IMPORT_ERROR = None
except Exception as e:
    export_clo_obj = None
    make_clo_obj_option = None
    CLO_EXPORT_OBJ_IMPORT_ERROR = e
BASE_ZPRJ_PATH = ""
GARMENT_INPUTS = []

# 이전 코드로 만든 10개 fabric sample 폴더
# 각 하위 폴더에 .zfab과 material.json이 있다고 가정
FABRIC_SAMPLE_ROOT = ""

# simulation/export 결과 저장 위치
OUT_DIR = ""
GS_DIR = ""
SAMPLE_DIR_TEMPLATE = ""
DRAPED_ZPRJ_FILE_NAME = ""
SAMPLE_SUMMARY_FILE_NAME = ""
DATASET_SUMMARY_JSON = ""

# render 설정
NUM_VIEWS = 24
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 1024
START_INDEX = 0

# simulation 설정
SIM_STEPS = 300

# True면 simulation 후 zprj 저장
SAVE_SIM_ZPRJ = True
MAX_SAMPLES = 0
STOP_ON_FIRST_FAILURE = True

# True면 CLO turntable rendering을 건너뜀. 기본 dataset 이미지는 Blender stage에서 만든다.
SKIP_RENDER = True

# Simulation 후 garment OBJ bundle(.obj, .mtl, textures)을 export.
EXPORT_OBJ = True
OBJ_FILE_NAME = ""
OBJ_EXPORT_FUNCTION_NAMES = [
    "ExportOBJW",
]
OBJ_EXPORT_INCLUDE_GARMENT = True
OBJ_EXPORT_INCLUDE_AVATAR = False
OBJ_EXPORT_SCALE = 0.01
CLO_VERSION = "2026.0.312"
EXPECT_BENDING_BIAS_PATCH = False
EXPECTED_BENDING_BIAS_FIELDS = []
FABRIC_PROPERTY_FIELD_GROUPS = {
    "stretch": ["fSuK", "fSvK", "fLeftShearK", "fLeftShearK_v2", "fRightShearK_v2", "fHK"],
    "bending": ["fBuK", "fBuK_v2", "fBvK", "fBvK_v2", "fBhK", "fBhK_v2"],
    "bending_shear": [
        "fBLeftShearK",
        "fBLeftShearK_v2",
        "fBRightShearK",
        "fBRightShearK_v2",
    ],
    "buckling": [
        "fBucklingStiffnessU",
        "fBucklingStiffnessV",
        "fBucklingStiffnessH",
        "fBucklingStiffnessLeftShear",
    ],
    "physical": ["fDensity", "fThickness", "fFriction"],
}


# =============================================================================
# IO
# =============================================================================

def safe_name(s):
    for ch in '<>:"/\\|?*':
        s = str(s).replace(ch, "_")
    return s.strip() or "unnamed"


def format_stage_template(template, **values):
    try:
        return template.format(**values)
    except Exception:
        return template


def read_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()

    if text is None or text.strip() == "":
        raise RuntimeError(f"JSON file is empty: {path}")

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        start = max(0, e.pos - 120)
        end = min(len(text), e.pos + 120)
        snippet = text[start:end].replace("\n", "\\n")
        raise RuntimeError(
            "Failed to parse JSON file.\n"
            f"Path   : {path}\n"
            f"Line   : {e.lineno}\n"
            f"Column : {e.colno}\n"
            f"Pos    : {e.pos}\n"
            f"Snippet: {snippet}"
        )


def try_read_json(path):
    try:
        return read_json(path), None
    except Exception as e:
        return None, str(e)


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def copy_file(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def deep_get(obj, keys, default=None):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def parse_bool(value, default=False):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def load_config(path):
    if not path:
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def resolve_config_path(path, output_root=""):
    if path is None or str(path).strip() == "":
        return ""
    resolved = os.path.expanduser(str(path))
    if not os.path.isabs(resolved) and output_root:
        resolved = os.path.join(output_root, resolved)
    return os.path.abspath(resolved)


def resolve_path_from_base(path, base_dir):
    if path is None or str(path).strip() == "":
        return ""
    resolved = os.path.expanduser(str(path))
    if not os.path.isabs(resolved) and base_dir:
        resolved = os.path.join(base_dir, resolved)
    return os.path.abspath(resolved)


def find_input_file(root_dir, extension, label):
    if not root_dir:
        return ""
    pattern = os.path.join(root_dir, f"*.{extension.lstrip('.')}")
    candidates = [path for path in glob.glob(pattern) if os.path.isfile(path)]
    if not candidates:
        return ""
    ext = extension.lstrip(".").lower()

    def rank(path):
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


def discover_input_files(root_dir, extension):
    if not root_dir or not os.path.exists(root_dir):
        return []
    ext = extension.lstrip(".").lower()
    found = []
    for dirpath, _, filenames in os.walk(root_dir):
        matches = sorted(
            os.path.join(dirpath, name)
            for name in filenames
            if name.lower().endswith("." + ext)
        )
        found.extend(matches)
    return [os.path.abspath(path) for path in sorted(found)]


def infer_garment_id(path, garments_dir="", fallback="garment"):
    stem = os.path.splitext(os.path.basename(path))[0]
    rel_parent = "."
    if garments_dir:
        try:
            rel_parent = os.path.relpath(os.path.dirname(path), garments_dir)
        except Exception:
            rel_parent = "."

    if rel_parent and rel_parent != ".":
        return safe_name(rel_parent.replace(os.sep, "_"))

    lower_stem = stem.lower()
    if "female" in lower_stem:
        return "female"
    if "male" in lower_stem:
        return "male"
    return safe_name(stem or fallback)


def discover_garment_inputs(config, output_root, fallback_zprj):
    entries = (
        deep_get(config, ["inputs", "garments"])
        or deep_get(config, ["stage_2_clo_simulation", "inputs", "garments"])
        or []
    )
    garments = []

    if isinstance(entries, list):
        for idx, entry in enumerate(entries):
            if isinstance(entry, str):
                path = entry
                garment_id = infer_garment_id(path, "", f"garment_{idx:03d}")
                metadata = {}
            elif isinstance(entry, dict):
                path = entry.get("zprj") or entry.get("path") or entry.get("base_zprj") or ""
                garment_id = safe_name(entry.get("id") or entry.get("name") or infer_garment_id(path, "", f"garment_{idx:03d}"))
                metadata = {k: v for k, v in entry.items() if k not in ("zprj", "path", "base_zprj")}
            else:
                continue
            if path:
                garments.append({
                    "garment_id": garment_id,
                    "zprj": resolve_config_path(path, output_root),
                    "metadata": metadata,
                })

    input_dir = (
        deep_get(config, ["inputs", "input_dir"])
        or deep_get(config, ["stage_2_clo_simulation", "inputs", "input_dir"])
        or "input"
    )
    input_dir = resolve_config_path(input_dir, output_root)
    garments_dir = (
        deep_get(config, ["inputs", "garments_dir"])
        or deep_get(config, ["stage_2_clo_simulation", "inputs", "garments_dir"])
        or os.path.join(input_dir, "garments")
    )
    if garments_dir:
        garments_dir = resolve_config_path(garments_dir, output_root)
        for path in discover_input_files(garments_dir, "zprj"):
            garment_id = infer_garment_id(path, garments_dir, f"garment_{len(garments):03d}")
            garments.append({
                "garment_id": garment_id,
                "zprj": path,
                "metadata": {"source": "garments_dir"},
            })

    if fallback_zprj and not garments:
        garments.append({
            "garment_id": "garment_000",
            "zprj": resolve_config_path(fallback_zprj, output_root),
            "metadata": {"source": "legacy_base_garment_zprj"},
        })

    deduped = []
    seen = set()
    for item in garments:
        key = os.path.normcase(os.path.abspath(item["zprj"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Run CLO simulation and export OBJ bundles.")
    parser.add_argument("--config", default="", help="Pipeline JSON config path.")
    parser.add_argument("--base_zprj", default="", help="Override base .zprj path.")
    parser.add_argument("--fabric_sample_root", default="", help="Override .zfab sample root.")
    parser.add_argument("--out_dir", default="", help="Override CLO output directory.")
    args, _ = parser.parse_known_args(argv)
    return args


def apply_config(config, args, config_dir=""):
    global BASE_ZPRJ_PATH, GARMENT_INPUTS, FABRIC_SAMPLE_ROOT, OUT_DIR, GS_DIR
    global SAMPLE_DIR_TEMPLATE, DRAPED_ZPRJ_FILE_NAME, SAMPLE_SUMMARY_FILE_NAME
    global DATASET_SUMMARY_JSON
    global NUM_VIEWS, IMAGE_WIDTH, IMAGE_HEIGHT, START_INDEX
    global SIM_STEPS, SAVE_SIM_ZPRJ, MAX_SAMPLES, STOP_ON_FIRST_FAILURE
    global SKIP_RENDER, EXPORT_OBJ
    global OBJ_FILE_NAME, OBJ_EXPORT_FUNCTION_NAMES
    global OBJ_EXPORT_INCLUDE_GARMENT, OBJ_EXPORT_INCLUDE_AVATAR
    global OBJ_EXPORT_SCALE
    global CLO_VERSION
    global EXPECT_BENDING_BIAS_PATCH, EXPECTED_BENDING_BIAS_FIELDS
    global FABRIC_PROPERTY_FIELD_GROUPS

    output_root = (
        deep_get(config, ["project", "output_dir"])
        or deep_get(config, ["project", "dataset_root"])
        or deep_get(config, ["paths", "output_dir"])
        or deep_get(config, ["paths", "dataset_root"])
        or deep_get(config, ["paths", "root_dir"])
        or ""
    )
    output_root = resolve_path_from_base(output_root, config_dir) if output_root else ""

    BASE_ZPRJ_PATH = (
        args.base_zprj
        or deep_get(config, ["inputs", "base_garment_zprj"])
        or deep_get(config, ["stage_2_clo_simulation", "inputs", "base_model_zprj"])
        or deep_get(config, ["clo", "base_zprj"])
        or deep_get(config, ["paths", "base_zprj"])
        or find_input_file(output_root, "zprj", "base zprj")
        or BASE_ZPRJ_PATH
    )
    GARMENT_INPUTS = discover_garment_inputs(config, output_root, BASE_ZPRJ_PATH)
    input_dir = (
        deep_get(config, ["inputs", "input_dir"])
        or deep_get(config, ["stage_2_clo_simulation", "inputs", "input_dir"])
        or "input"
    )
    input_dir = resolve_config_path(input_dir, output_root)
    fabrics_dir = (
        deep_get(config, ["inputs", "fabrics_dir"])
        or deep_get(config, ["stage_2_clo_simulation", "inputs", "fabrics_dir"])
        or os.path.join(input_dir, "fabrics")
    )
    fabrics_dir = resolve_config_path(fabrics_dir, output_root)
    FABRIC_SAMPLE_ROOT = (
        args.fabric_sample_root
        or deep_get(config, ["stage_2_clo_simulation", "inputs", "fabric_dir"])
        or deep_get(config, ["stage_2_clo_simulation", "inputs", "fabrics_dir"])
        or fabrics_dir
        or deep_get(config, ["stage_1_fabric_sampler", "outputs", "fabric_dir"])
        or deep_get(config, ["clo", "fabric_sample_root"])
        or deep_get(config, ["paths", "zfab_output_dir"])
        or (os.path.join(output_root, deep_get(config, ["naming", "fabric_dir"], "")) if output_root and deep_get(config, ["naming", "fabric_dir"], "") else "")
        or FABRIC_SAMPLE_ROOT
    )
    OUT_DIR = (
        args.out_dir
        or deep_get(config, ["stage_2_clo_simulation", "outputs", "draped_dir"])
        or deep_get(config, ["clo", "output_dir"])
        or deep_get(config, ["paths", "clo_output_dir"])
        or (os.path.join(output_root, deep_get(config, ["naming", "draped_dir"], "")) if output_root and deep_get(config, ["naming", "draped_dir"], "") else "")
        or OUT_DIR
    )
    GS_DIR = (
        deep_get(config, ["stage_4_3dgs_training", "outputs", "gs_dir"])
        or deep_get(config, ["stage_5_3dgs_training", "outputs", "gs_dir"])
        or deep_get(config, ["3dgs_training", "output_dir"])
        or (os.path.join(output_root, deep_get(config, ["naming", "gs_dir"], "")) if output_root and deep_get(config, ["naming", "gs_dir"], "") else "")
        or GS_DIR
    )
    SAMPLE_DIR_TEMPLATE = str(
        deep_get(
            config,
            ["stage_2_clo_simulation", "outputs", "sample_dir_template"],
            deep_get(config, ["naming", "sample_dir_template"], SAMPLE_DIR_TEMPLATE),
        )
    )
    DRAPED_ZPRJ_FILE_NAME = str(
        deep_get(
            config,
            ["stage_2_clo_simulation", "outputs", "draped_zprj_file_name"],
            deep_get(config, ["naming", "draped_zprj_file"], DRAPED_ZPRJ_FILE_NAME),
        )
    )
    SAMPLE_SUMMARY_FILE_NAME = str(
        deep_get(
            config,
            ["stage_2_clo_simulation", "outputs", "sample_summary_file_name"],
            deep_get(config, ["naming", "sample_summary_file"], SAMPLE_SUMMARY_FILE_NAME),
        )
    )
    DATASET_SUMMARY_JSON = str(
        deep_get(
            config,
            ["stage_2_clo_simulation", "outputs", "dataset_summary_json"],
            os.path.join(OUT_DIR, "dataset_summary.json"),
        )
    )

    NUM_VIEWS = int(deep_get(config, ["clo", "num_views"], NUM_VIEWS))
    IMAGE_WIDTH = int(deep_get(config, ["clo", "image_width"], IMAGE_WIDTH))
    IMAGE_HEIGHT = int(deep_get(config, ["clo", "image_height"], IMAGE_HEIGHT))
    START_INDEX = int(deep_get(config, ["clo", "start_index"], START_INDEX))
    SIM_STEPS = int(
        deep_get(
            config,
            ["stage_2_clo_simulation", "settings", "sim_steps"],
            deep_get(config, ["clo_simulation", "sim_steps"], deep_get(config, ["clo", "sim_steps"], SIM_STEPS)),
        )
    )
    SAVE_SIM_ZPRJ = parse_bool(
        deep_get(
            config,
            ["stage_2_clo_simulation", "settings", "save_sim_zprj"],
            deep_get(
                config,
                ["clo_simulation", "save_sim_zprj"],
                deep_get(config, ["clo", "save_sim_zprj"], SAVE_SIM_ZPRJ),
            ),
        ),
        SAVE_SIM_ZPRJ,
    )
    MAX_SAMPLES = int(
        deep_get(
            config,
            ["stage_2_clo_simulation", "settings", "max_samples"],
            deep_get(config, ["clo_simulation", "max_samples"], deep_get(config, ["clo", "max_samples"], MAX_SAMPLES)),
        )
    )
    STOP_ON_FIRST_FAILURE = bool(
        deep_get(
            config,
            ["stage_2_clo_simulation", "settings", "stop_on_first_failure"],
            deep_get(config, ["clo_simulation", "stop_on_first_failure"], deep_get(config, ["clo", "stop_on_first_failure"], STOP_ON_FIRST_FAILURE)),
        )
    )
    SKIP_RENDER = bool(
        deep_get(
            config,
            ["stage_2_clo_simulation", "settings", "skip_render"],
            deep_get(config, ["clo_simulation", "skip_render"], deep_get(config, ["clo", "skip_render"], SKIP_RENDER)),
        )
    )
    EXPORT_OBJ = bool(
        deep_get(
            config,
            ["stage_2_clo_simulation", "settings", "export_obj"],
            deep_get(config, ["clo_simulation", "export_obj"], deep_get(config, ["clo", "export_obj"], EXPORT_OBJ)),
        )
    )
    OBJ_FILE_NAME = str(
        deep_get(
            config,
            ["naming", "obj_file"],
            deep_get(config, ["clo", "obj_file_name"], OBJ_FILE_NAME),
        )
    )
    configured_obj_export_functions = list(
        deep_get(config, ["clo", "obj_export_function_names"], OBJ_EXPORT_FUNCTION_NAMES)
    )
    OBJ_EXPORT_FUNCTION_NAMES = [
        name for name in configured_obj_export_functions
        if str(name).strip() == "ExportOBJW"
    ] or ["ExportOBJW"]
    OBJ_EXPORT_INCLUDE_GARMENT = bool(
        deep_get(config, ["clo", "obj_export_include_garment"], OBJ_EXPORT_INCLUDE_GARMENT)
    )
    OBJ_EXPORT_INCLUDE_AVATAR = bool(
        deep_get(config, ["clo", "obj_export_include_avatar"], OBJ_EXPORT_INCLUDE_AVATAR)
    )
    OBJ_EXPORT_SCALE = float(deep_get(config, ["clo", "obj_export_scale"], OBJ_EXPORT_SCALE))
    CLO_VERSION = str(deep_get(config, ["clo", "clo_version"], CLO_VERSION))
    uses_original_fabric_pool = (
        os.path.normcase(os.path.abspath(FABRIC_SAMPLE_ROOT))
        == os.path.normcase(os.path.abspath(fabrics_dir))
    )
    EXPECT_BENDING_BIAS_PATCH = (not uses_original_fabric_pool) and bool(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "patch_bending_bias"],
            deep_get(config, ["fabric_sampler", "patch_bending_bias"], False),
        )
    )
    EXPECTED_BENDING_BIAS_FIELDS = list(
        deep_get(
            config,
            ["stage_1_fabric_sampler", "settings", "bias_fields"],
            deep_get(config, ["fabric_sampler", "bias_fields"], []),
        )
    )
    configured_field_groups = (
        deep_get(config, ["stage_2_clo_simulation", "material_gt", "field_groups"])
        or deep_get(config, ["fabric_gt", "field_groups"])
        or None
    )
    if isinstance(configured_field_groups, dict):
        FABRIC_PROPERTY_FIELD_GROUPS = {
            str(group): [str(field) for field in fields]
            for group, fields in configured_field_groups.items()
            if isinstance(fields, list)
        }


def ensure_clo_api():
    if CLO_API_IMPORT_ERROR is None:
        return
    raise RuntimeError(
        "CLO Python API modules are not available. "
        "Run this script inside CLO Python Script Editor or configure a CLO Python command. "
        f"Import error: {CLO_API_IMPORT_ERROR}"
    )


# =============================================================================
# Dataset sample discovery
# =============================================================================

def find_sample_folders(root):
    """
    root 아래에서 .zfab을 가진 sample 폴더를 찾음.
    """
    root = os.path.abspath(root)
    root_level_zfabs = sorted(glob.glob(os.path.join(root, "*.zfab")))
    if root_level_zfabs:
        return root_level_zfabs

    sample_dirs = []

    for dirpath, dirnames, filenames in os.walk(root):
        has_zfab = any(fn.lower().endswith(".zfab") for fn in filenames)
        if has_zfab:
            sample_dirs.append(dirpath)

    sample_dirs = sorted(sample_dirs)
    return sample_dirs


def get_zfab_path(sample_dir):
    if os.path.isfile(sample_dir) and sample_dir.lower().endswith(".zfab"):
        return sample_dir

    zfabs = sorted(glob.glob(os.path.join(sample_dir, "*.zfab")))
    if len(zfabs) == 0:
        raise RuntimeError(f"No .zfab found in {sample_dir}")
    if len(zfabs) > 1:
        print(f"[Warning] multiple .zfab found. Use first: {zfabs[0]}")
    return zfabs[0]


def get_output_fabric_material_json_path(out_dir, fabric_id):
    return os.path.join(out_dir, safe_name(fabric_id), "material.json")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def find_exact_key_offsets(data, key):
    key_b = key.encode("ascii")
    offsets = []
    start = 0
    while start < len(data):
        idx = data.find(key_b, start)
        if idx < 0:
            break
        val_off = idx + len(key_b)
        start = idx + 1
        if val_off + 4 > len(data):
            continue
        if data[val_off:val_off + 3] == b"_v2":
            continue
        offsets.append(val_off)
    return offsets


def read_float_le(data, offset):
    return struct.unpack("<f", data[offset:offset + 4])[0]


def scan_fields_in_fab(data, field_names):
    result = {}
    for name in field_names:
        values = []
        for off in find_exact_key_offsets(data, name):
            values.append({
                "value_offset": off,
                "value_float_le": read_float_le(data, off),
                "raw_hex": data[off:off + 4].hex(),
            })
        result[name] = values
    return result


def last_scanned_value(field_scans, field_names):
    for field in field_names:
        values = field_scans.get(field, [])
        if values:
            return values[-1].get("value_float_le")
    return None


def flatten_zfab_field_scans(fab_scans):
    flattened = {}
    for fab_file, field_scan in fab_scans.items():
        for field, values in field_scan.items():
            if values and field not in flattened:
                flattened[field] = values
    return flattened


def clean_empty_values(value):
    if isinstance(value, dict):
        cleaned = {
            key: clean_empty_values(item)
            for key, item in value.items()
        }
        return {
            key: item
            for key, item in cleaned.items()
            if item is not None and item != {}
        }
    return value


def build_material_gt_from_zfab(sample_dir, zfab_path, fabric_id, bend_id, sample_id):
    field_groups = {k: list(v) for k, v in FABRIC_PROPERTY_FIELD_GROUPS.items()}
    field_names = sorted({field for fields in field_groups.values() for field in fields})
    if not zipfile.is_zipfile(zfab_path):
        raise RuntimeError(f"Input is not a valid .zfab zip: {zfab_path}")

    fab_scans = {}
    with zipfile.ZipFile(zfab_path, "r") as z:
        for info in z.infolist():
            if info.filename.lower().endswith(".fab"):
                data = z.read(info.filename)
                fab_scans[info.filename] = scan_fields_in_fab(data, field_names)

    if not fab_scans:
        raise RuntimeError(f"No .fab file found inside zfab: {zfab_path}")

    flat_scan = flatten_zfab_field_scans(fab_scans)
    density = last_scanned_value(flat_scan, ["fDensity"])
    field_map = {
        "stretch.warp": ["fSuK"],
        "stretch.weft": ["fSvK"],
        "shear": ["fRightShearK_v2", "fLeftShearK_v2", "fHK"],
        "bending.warp": ["fBuK_v2", "fBuK"],
        "bending.weft": ["fBvK_v2", "fBvK"],
        "bending.bias": ["fBRightShearK_v2", "fBLeftShearK_v2", "fBhK_v2", "fBhK"],
        "buckling.warp": ["fBucklingStiffnessU"],
        "buckling.weft": ["fBucklingStiffnessV"],
        "buckling.bias": ["fBucklingStiffnessH"],
        "density": ["fDensity"],
        "weight": ["fDensity"],
        "thickness": ["fThickness"],
        "friction": ["fFriction"],
    }
    actual = {
        "stretch": {
            "warp": last_scanned_value(flat_scan, field_map["stretch.warp"]),
            "weft": last_scanned_value(flat_scan, field_map["stretch.weft"]),
        },
        "shear": last_scanned_value(flat_scan, field_map["shear"]),
        "bending": {
            "warp": last_scanned_value(flat_scan, field_map["bending.warp"]),
            "weft": last_scanned_value(flat_scan, field_map["bending.weft"]),
            "bias": last_scanned_value(flat_scan, field_map["bending.bias"]),
        },
        "buckling": {
            "warp": last_scanned_value(flat_scan, field_map["buckling.warp"]),
            "weft": last_scanned_value(flat_scan, field_map["buckling.weft"]),
            "bias": last_scanned_value(flat_scan, field_map["buckling.bias"]),
        },
        "density": density,
        "weight": round(density * 1000000.0, 6) if density is not None else None,
        "thickness": last_scanned_value(flat_scan, field_map["thickness"]),
        "friction": last_scanned_value(flat_scan, field_map["friction"]),
    }
    actual = clean_empty_values(actual)
    actual.setdefault("density", density)
    actual.setdefault("weight", round(density * 1000000.0, 6) if density is not None else None)

    return {
        "sample_id": sample_id,
        "fabric_id": fabric_id,
        "bend_id": bend_id,
        "source_sample_dir": sample_dir,
        "source_zfab": zfab_path,
        "zfab_sha256": sha256_file(zfab_path),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "generated_by": "scripts/01_clo_make_dataset.py",
        "gt_source": "scanned_from_zfab_fab_fields",
        "actual": actual,
        "internal_fields": {
            "field_map": field_map,
            "fab_files": list(fab_scans.keys()),
        },
    }


def infer_variant_ids(sample_dir, zfab_path, material_data=None):
    material_data = material_data or {}
    fabric_id = material_data.get("fabric_id")
    bend_id = material_data.get("bend_id") or material_data.get("variant_id")
    sample_id = material_data.get("sample_id")

    rel_parts = []
    try:
        rel = os.path.relpath(sample_dir if os.path.isdir(sample_dir) else os.path.dirname(zfab_path), FABRIC_SAMPLE_ROOT)
        rel_parts = [part for part in rel.split(os.sep) if part and part != "."]
    except Exception:
        pass

    if not fabric_id:
        if len(rel_parts) >= 2:
            fabric_id = rel_parts[-2]
        elif len(rel_parts) == 1:
            fabric_id = rel_parts[0]
        else:
            fabric_id = os.path.splitext(os.path.basename(zfab_path))[0]
    if not bend_id:
        if len(rel_parts) >= 2:
            bend_id = rel_parts[-1]
        else:
            bend_id = "original"

    fabric_id = safe_name(fabric_id)
    bend_id = safe_name(bend_id)
    sample_id = safe_name(sample_id or f"{fabric_id}__{bend_id}")
    return fabric_id, bend_id, sample_id


def build_fabric_variant_records(sample_dirs):
    variants = []
    for idx, sample_dir in enumerate(sample_dirs):
        zfab_path = get_zfab_path(sample_dir)
        material_src = None
        material_json_error = None
        fabric_id, bend_id, sample_id = infer_variant_ids(sample_dir, zfab_path, None)
        material_json_generated = False
        material_generation_error = None
        material_data = None
        try:
            material_data = build_material_gt_from_zfab(
                sample_dir,
                zfab_path,
                fabric_id,
                bend_id,
                sample_id,
            )
        except Exception as e:
            material_generation_error = str(e)
        variants.append({
            "variant_index": idx,
            "source_sample_dir": sample_dir,
            "zfab_path": zfab_path,
            "material_json": material_src,
            "material_json_generated": material_json_generated,
            "material_generation_error": material_generation_error,
            "material_json_error": material_json_error,
            "material_data": material_data,
            "fabric_id": fabric_id,
            "bend_id": bend_id,
            "sample_id": sample_id,
        })
    return variants


def validate_fabric_variant_metadata(fabric_variants):
    if not EXPECT_BENDING_BIAS_PATCH:
        return

    stale_variants = []
    missing_metadata = []
    stale_field_variants = []
    expected_bias_fields = {str(field) for field in EXPECTED_BENDING_BIAS_FIELDS}
    for variant in fabric_variants:
        material_data = variant.get("material_data")
        if not isinstance(material_data, dict):
            missing_metadata.append(variant)
            continue

        ui_values = material_data.get("ui") if isinstance(material_data.get("ui"), dict) else {}
        actual_values = material_data.get("actual") if isinstance(material_data.get("actual"), dict) else {}
        actual_bending = actual_values.get("bending") if isinstance(actual_values.get("bending"), dict) else {}
        has_bias = "bending_bias" in ui_values or "bending_bias" in actual_values or "bias" in actual_bending
        if not has_bias:
            stale_variants.append(variant)
            continue

        internal_fields = material_data.get("internal_fields") if isinstance(material_data.get("internal_fields"), dict) else {}
        material_bias_fields = {str(field) for field in internal_fields.get("bias_fields", [])}
        if expected_bias_fields and not expected_bias_fields.issubset(material_bias_fields):
            stale_field_variants.append(variant)

    if missing_metadata:
        print(
            "[Warning] Some fabric variants have no material metadata; "
            "cannot verify whether bias bending was patched."
        )

    if stale_variants:
        examples = "\n".join(
            f"  - {item.get('source_sample_dir')}"
            for item in stale_variants[:5]
        )
        raise RuntimeError(
            "Fabric variants look stale: config expects bending bias to be patched, "
            "but material.json has no ui/actual.bending_bias.\n"
            "Regenerate fabric variants first:\n"
            "  python scripts\\clo_fab_sampler.py --config dataset_config.json\n"
            "Examples:\n"
            f"{examples}"
        )

    if stale_field_variants:
        examples = "\n".join(
            f"  - {item.get('source_sample_dir')}"
            for item in stale_field_variants[:5]
        )
        raise RuntimeError(
            "Fabric variants look stale: config expects expanded bending bias fields, "
            "but material.json was generated with an older bias_fields list.\n"
            "Regenerate fabric variants first:\n"
            "  python scripts\\clo_fab_sampler.py --config dataset_config.json\n"
            "Examples:\n"
            f"{examples}"
        )


def build_dataset_jobs(garments, fabric_variants):
    jobs = []
    for variant in fabric_variants:
        for garment_index, garment in enumerate(garments):
            garment_id = safe_name(garment.get("garment_id") or f"garment_{garment_index:03d}")
            sample_id = f"{variant['fabric_id']}__{garment_id}"
            jobs.append({
                "sample_index": len(jobs),
                "sample_id": sample_id,
                "garment_index": garment_index,
                "garment_id": garment_id,
                "body_id": garment_id,
                "garment_zprj": garment["zprj"],
                "garment_metadata": garment.get("metadata", {}),
                "fabric_variant": variant,
            })
    return jobs


# =============================================================================
# CLO wrappers
# =============================================================================

def new_project_and_import_base(base_zprj_path=None):
    """
    매 sample마다 base ZPRJ를 다시 열어 drape 초기 상태를 동일하게 만듦.
    """
    try:
        utility_api.NewProject()
    except Exception as e:
        print(f"[Warning] NewProject failed or unavailable: {e}")

    base_zprj_path = base_zprj_path or BASE_ZPRJ_PATH
    result = import_api.ImportFile(base_zprj_path)

    # CLO API는 성공 시 None/string/bool 등 버전별로 다를 수 있음
    if result == "" or result is False:
        raise RuntimeError(f"Import base ZPRJ failed: {base_zprj_path}")

    try:
        utility_api.Refresh3DWindow()
    except Exception:
        pass


def add_and_assign_fabric_to_all_patterns(zfab_path):
    """
    .zfab을 Object Browser에 추가하고, 모든 pattern에 assign.
    """
    fabric_idx = fabric_api.AddFabric(zfab_path)

    if fabric_idx is None or fabric_idx < 0:
        raise RuntimeError(f"AddFabric failed: {zfab_path}")

    pattern_count = pattern_api.GetPatternCount()

    if pattern_count <= 0:
        raise RuntimeError("No pattern found in current project.")

    for pattern_idx in range(pattern_count):
        ok = None

        # assignOption 3: all colorways linked
        # 안 되면 current colorway 방식으로 fallback
        try:
            ok = fabric_api.AssignFabricToPattern(fabric_idx, pattern_idx, 3)
        except Exception:
            try:
                ok = fabric_api.AssignFabricToPattern(fabric_idx, pattern_idx)
            except Exception as e:
                raise RuntimeError(
                    f"AssignFabricToPattern failed: fabric={fabric_idx}, pattern={pattern_idx}, err={e}"
                )

        if ok is False:
            raise RuntimeError(
                f"AssignFabricToPattern returned False: fabric={fabric_idx}, pattern={pattern_idx}"
            )

    try:
        utility_api.Refresh3DWindow()
    except Exception:
        pass

    return fabric_idx, pattern_count


def setup_simulation():
    """
    안정적인 batch simulation 설정.
    필요하면 여기만 조정.
    """
    try:
        # 0: Normal, 1: Animation Stable, 2: Fitting Accurate, 3: FAST GPU
        # 0: CPU, 1: FAST GPU
        utility_api.SetSimulationQuality(1, 0)
    except Exception as e:
        print(f"[Warning] SetSimulationQuality failed: {e}")

    try:
        utility_api.SetSimulationTimeStep(0.03333)
    except Exception:
        pass

    try:
        utility_api.SetSimulationNumberOfSimulation(1)
    except Exception:
        pass

    try:
        utility_api.SetSimulationCGIterationCount(100)
    except Exception:
        pass


def simulate_current_scene(steps):
    """
    현재 scene simulation.
    """
    setup_simulation()

    ok = utility_api.Simulate(steps)

    if ok is False:
        raise RuntimeError(f"Simulate({steps}) failed")

    try:
        utility_api.Refresh3DWindow()
    except Exception:
        pass


def export_turntable_images(out_image_dir):
    """
    현재 scene의 turntable image를 저장.
    ExportTurntableImages signature가 CLO 버전마다 달라서 여러 방식 시도.
    """
    os.makedirs(out_image_dir, exist_ok=True)

    prefix = os.path.join(out_image_dir, "view")

    last_err = None
    paths = None

    candidates = [
        lambda: export_api.ExportTurntableImages(
            prefix, NUM_VIEWS, IMAGE_WIDTH, IMAGE_HEIGHT, START_INDEX
        ),
        lambda: export_api.ExportTurntableImages(
            out_image_dir, NUM_VIEWS, IMAGE_WIDTH, IMAGE_HEIGHT, START_INDEX
        ),
        lambda: export_api.ExportTurntableImages(NUM_VIEWS),
    ]

    for fn in candidates:
        try:
            paths = fn()
            if paths and len(paths) > 0:
                break
        except Exception as e:
            last_err = e
            paths = None

    if not paths:
        raise RuntimeError(f"ExportTurntableImages failed: {last_err}")

    # 반환 path가 temp folder일 수도 있으므로 out_image_dir로 복사
    saved = []
    flat_paths = flatten_path_list(paths)

    for i, src in enumerate(flat_paths):
        if not src or not os.path.exists(src):
            continue

        ext = os.path.splitext(src)[1]
        if ext == "":
            ext = ".png"

        dst = os.path.join(out_image_dir, f"view_{i:03d}{ext}")
        if os.path.abspath(src) != os.path.abspath(dst):
            copy_file(src, dst)

        saved.append(dst)

    if len(saved) == 0:
        # 혹시 함수가 직접 out_image_dir에 저장했는데 반환 path가 이상한 경우
        direct_imgs = []
        for ext in ["*.png", "*.jpg", "*.jpeg"]:
            direct_imgs.extend(glob.glob(os.path.join(out_image_dir, ext)))
        direct_imgs = sorted(direct_imgs)

        if len(direct_imgs) == 0:
            raise RuntimeError("No images were exported by ExportTurntableImages.")

        saved = direct_imgs

    return saved


def export_rendering_image_fallback(out_image_dir):
    """
    Turntable이 실패할 때 단일/렌더링 이미지 export fallback.
    """
    os.makedirs(out_image_dir, exist_ok=True)

    out_prefix = os.path.join(out_image_dir, "render")

    last_err = None
    paths = None

    candidates = [
        lambda: export_api.ExportRenderingImage(out_prefix, False, 0),
        lambda: export_api.ExportRenderingImage(out_prefix, 0),
        lambda: export_api.ExportRenderingImage(False, 0),
        lambda: export_api.ExportRenderingImage(False),
    ]

    for fn in candidates:
        try:
            paths = fn()
            if paths:
                break
        except Exception as e:
            last_err = e

    if not paths:
        raise RuntimeError(f"ExportRenderingImage failed: {last_err}")

    flat_paths = flatten_path_list(paths)
    saved = []

    for i, src in enumerate(flat_paths):
        if not src or not os.path.exists(src):
            continue

        ext = os.path.splitext(src)[1] or ".png"
        dst = os.path.join(out_image_dir, f"render_{i:03d}{ext}")

        if os.path.abspath(src) != os.path.abspath(dst):
            copy_file(src, dst)

        saved.append(dst)

    return saved


def flatten_path_list(x):
    """
    CLO API가 list[str] 또는 list[list[str]]를 반환할 수 있어서 flatten.
    """
    out = []

    if x is None:
        return out

    if isinstance(x, str):
        return [x]

    if isinstance(x, (list, tuple)):
        for item in x:
            out.extend(flatten_path_list(item))

    return out


def export_sim_zprj(out_path):
    """
    simulation 결과 project 저장.
    """
    result = export_api.ExportZPrj(out_path, False)

    if result == "" or result is False:
        # fallback
        result = export_api.ExportZPrj(out_path)

    if result == "" or result is False:
        raise RuntimeError(f"ExportZPrj failed: {out_path}")

    return out_path if os.path.exists(out_path) else result


def export_api_function_names():
    if export_api is None:
        return []
    return sorted(
        name
        for name in dir(export_api)
        if "export" in name.lower() or "obj" in name.lower()
    )


def export_api_function_details():
    details = {}
    if export_api is None:
        return details
    for name in export_api_function_names():
        value = getattr(export_api, name, None)
        details[name] = {
            "repr": repr(value),
            "doc": getattr(value, "__doc__", None),
        }
    return details


def api_module_symbol_details():
    modules = [
        ("export_api", export_api),
        ("import_api", import_api),
        ("fabric_api", fabric_api),
        ("pattern_api", pattern_api),
        ("utility_api", utility_api),
    ]
    details = {}
    for module_name, module in modules:
        if module is None:
            continue
        try:
            names = [name for name in dir(module) if not name.startswith("__")]
        except Exception as e:
            details[module_name] = {"error": repr(e)}
            continue
        option_like = [
            name for name in names
            if "option" in name.lower() or "obj" in name.lower() or "export" in name.lower()
        ]
        details[module_name] = {
            "option_export_obj_symbols": sorted(option_like),
        }
    try:
        module = __import__("CLOAPIInterface")
        names = [name for name in dir(module) if not name.startswith("__")]
        option_like = [
            name for name in names
            if "option" in name.lower() or "obj" in name.lower() or "export" in name.lower()
        ]
        details["CLOAPIInterface"] = {
            "option_export_obj_symbols": sorted(option_like),
        }
    except Exception as e:
        details["CLOAPIInterface"] = {"error": repr(e)}
    return details


def resolve_texture_path(ref, base_dir):
    ref = ref.strip().strip('"').strip("'")
    if not ref:
        return None
    ref = ref.replace("/", os.sep).replace("\\", os.sep)
    if os.path.isabs(ref):
        path = os.path.normpath(ref)
    else:
        path = os.path.normpath(os.path.join(base_dir, ref))
    return path if os.path.exists(path) else None


def parse_mtl_texture_paths(mtl_path):
    diffuse_path = None
    normal_path = None
    if not mtl_path or not os.path.exists(mtl_path):
        return diffuse_path, normal_path

    mtl_dir = os.path.dirname(mtl_path)
    with open(mtl_path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            key = parts[0].lower()
            if len(parts) < 2:
                continue
            texture_path = resolve_texture_path(parts[-1], mtl_dir)
            if texture_path is None:
                continue
            if key in ("map_kd", "map_ka", "map_basecolor", "map_albedo") and diffuse_path is None:
                diffuse_path = texture_path
            if key in ("map_bump", "bump", "map_normal", "norm", "map_norm") and normal_path is None:
                normal_path = texture_path

    return diffuse_path, normal_path


def find_first_existing(patterns):
    paths = []
    for pattern in patterns:
        paths.extend(glob.glob(pattern))
    paths = [path for path in paths if os.path.exists(path)]
    if not paths:
        return None
    paths.sort(key=lambda p: (os.path.getmtime(p), p), reverse=True)
    return paths[0]


def collect_obj_bundle(out_sample_dir, preferred_obj_path=None):
    obj_path = preferred_obj_path if preferred_obj_path and os.path.exists(preferred_obj_path) else None
    if obj_path is None:
        obj_candidates = glob.glob(os.path.join(out_sample_dir, "*.obj"))
        obj_candidates.sort(key=lambda p: (os.path.getmtime(p), p), reverse=True)
        obj_path = obj_candidates[0] if obj_candidates else None

    mtl_path = None
    diffuse_path = None
    normal_path = None

    if obj_path and os.path.exists(obj_path):
        obj_dir = os.path.dirname(obj_path)
        with open(obj_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if line.lower().startswith("mtllib "):
                    ref = line.split(None, 1)[1]
                    mtl_path = resolve_texture_path(ref, obj_dir)
                    break

    if mtl_path is None:
        mtl_path = find_first_existing([os.path.join(out_sample_dir, "*.mtl")])

    if mtl_path:
        diffuse_path, normal_path = parse_mtl_texture_paths(mtl_path)

    if diffuse_path is None:
        diffuse_path = find_first_existing([
            os.path.join(out_sample_dir, "*diffuse*.png"),
            os.path.join(out_sample_dir, "*albedo*.png"),
            os.path.join(out_sample_dir, "*basecolor*.png"),
            os.path.join(out_sample_dir, "*base_color*.png"),
            os.path.join(out_sample_dir, "*diffuse*.jpg"),
            os.path.join(out_sample_dir, "*albedo*.jpg"),
        ])
    if normal_path is None:
        normal_path = find_first_existing([
            os.path.join(out_sample_dir, "*normal*.png"),
            os.path.join(out_sample_dir, "*bump*.png"),
            os.path.join(out_sample_dir, "*normal*.jpg"),
            os.path.join(out_sample_dir, "*bump*.jpg"),
        ])

    bundle_files = []
    for path in (obj_path, mtl_path, diffuse_path, normal_path):
        if path and path not in bundle_files:
            bundle_files.append(path)

    return {
        "obj_path": obj_path,
        "mtl_path": mtl_path,
        "diffuse_path": diffuse_path,
        "normal_path": normal_path,
        "files": bundle_files,
    }


def make_clo_obj_option_compatible(option_kwargs):
    try:
        signature = inspect.signature(make_clo_obj_option)
        parameters = signature.parameters
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        if accepts_kwargs:
            filtered_kwargs = dict(option_kwargs)
        else:
            filtered_kwargs = {
                key: value
                for key, value in option_kwargs.items()
                if key in parameters
            }
    except Exception:
        filtered_kwargs = {
            key: option_kwargs[key]
            for key in ("export_garment", "export_avatar", "single_object", "include_hidden", "scale", "save_in_zip")
            if key in option_kwargs
        }

    return make_clo_obj_option(**filtered_kwargs)


def export_obj_bundle(out_sample_dir, zfab_path=None):
    os.makedirs(out_sample_dir, exist_ok=True)
    out_obj_path = os.path.abspath(os.path.join(out_sample_dir, OBJ_FILE_NAME))
    if export_clo_obj is None or make_clo_obj_option is None:
        raise RuntimeError(f"Failed to import utils.clo_export_obj: {repr(CLO_EXPORT_OBJ_IMPORT_ERROR)}")

    option_kwargs = {
        "export_garment": OBJ_EXPORT_INCLUDE_GARMENT,
        "export_avatar": OBJ_EXPORT_INCLUDE_AVATAR,
        "export_light": False,
        "export_fabric": True,
        "single_object": True,
        "include_hidden": False,
        "scale": OBJ_EXPORT_SCALE,
        "save_in_zip": False,
        "show_dialog": False,
    }
    option, option_log = make_clo_obj_option_compatible(option_kwargs)
    option_log["requested"] = {
        "clo_version": CLO_VERSION,
        "function_candidates": OBJ_EXPORT_FUNCTION_NAMES,
        "include_garment": OBJ_EXPORT_INCLUDE_GARMENT,
        "include_avatar": OBJ_EXPORT_INCLUDE_AVATAR,
        "scale": OBJ_EXPORT_SCALE,
        "export_fabric": True,
        "show_dialog": False,
    }

    export_result = export_clo_obj(
        out_obj_path,
        function_names=OBJ_EXPORT_FUNCTION_NAMES,
        option=option,
        export_api_module=export_api,
        collect_callback=lambda: collect_obj_bundle(out_sample_dir, out_obj_path),
    )
    attempts = export_result["attempts"]

    if export_result["ok"]:
        bundle = export_result["bundle"]
        success_option_log = option_log
        bundle.update({
            "export_function": export_result["function"],
            "export_signature": export_result["signature"],
            "raw_result": str(export_result["result"]),
            "import_export_option": success_option_log,
            "post_processing": "none",
        })
        return bundle

    error_record = {
        "requested_obj_path": out_obj_path,
        "attempts": attempts,
        "import_export_option": option_log,
        "available_export_api_functions": export_api_function_names(),
        "available_export_api_function_details": export_api_function_details(),
        "api_module_symbol_details": api_module_symbol_details(),
        "dialog_fallback_enabled": False,
    }
    write_json(os.path.join(out_sample_dir, "obj_export_error.json"), error_record)
    raise RuntimeError(
        "OBJ export failed. See obj_export_error.json. "
        f"Available export functions: {error_record['available_export_api_functions']}"
    )


def safe_call(desc, fn):
    try:
        fn()
        print(f"[OK] {desc}")
        return True
    except Exception as e:
        print(f"[Skip] {desc}: {e}")
        return False


def hide_avatar_for_render():
    """
    Simulation에는 avatar가 필요하므로 simulation 후 render 직전에만 숨긴다.
    """
    # 전체 avatar hide
    safe_call(
        "SetShowHideAvatar(False)",
        lambda: utility_api.SetShowHideAvatar(False)
    )

    # 버전에 따라 index 버전만 동작할 수 있어서 fallback
    for avatar_idx in range(10):
        safe_call(
            f"SetShowHideAvatar(False, {avatar_idx})",
            lambda idx=avatar_idx: utility_api.SetShowHideAvatar(False, idx)
        )


def hide_unwanted_display_lines():
    """
    렌더링에 seam/internal/topstitch/measurement/pin/thread/3D pen 등이 보이지 않도록 설정.
    """

    # Schematic render 자체 off
    safe_call(
        "SetSchematicRender(False)",
        lambda: utility_api.SetSchematicRender(False)
    )

    # Schematic line options
    safe_call(
        "SetShowSchematicSilhouetteLine(False)",
        lambda: utility_api.SetShowSchematicSilhouetteLine(False)
    )
    safe_call(
        "SetShowSchematicSeamLine(False)",
        lambda: utility_api.SetShowSchematicSeamLine(False)
    )
    safe_call(
        "SetShowSchematicInternalLine(False)",
        lambda: utility_api.SetShowSchematicInternalLine(False)
    )
    safe_call(
        "SetShowSchematicTopstitchLine(False)",
        lambda: utility_api.SetShowSchematicTopstitchLine(False)
    )

    # Garment display properties
    # CLO 문서 기준:
    # 0: Garment
    # 1: Archived Pattern
    # 2: Seamlines
    # 3: Internal Lines
    # 4: ShowBaselines
    # 5: 3D Pen (Garment)
    # 6: Threads
    # 7: Pins
    # 8: Garment Measurements
    # 9: 2D Measurements
    # 10: Garment Fitting Suit
    # 11: All
    #
    # 0은 garment 자체이므로 True 유지.
    safe_call(
        "SetGarmentDisplayProperties(0, True)",
        lambda: utility_api.SetGarmentDisplayProperties(0, True)
    )

    hide_options = [
        1,  # Archived Pattern
        2,  # Seamlines
        3,  # Internal Lines
        4,  # Baselines
        5,  # 3D Pen
        6,  # Threads
        7,  # Pins
        8,  # Garment Measurements
        9,  # 2D Measurements
        10, # Garment Fitting Suit
    ]

    for opt in hide_options:
        safe_call(
            f"SetGarmentDisplayProperties({opt}, False)",
            lambda option=opt: utility_api.SetGarmentDisplayProperties(option, False)
        )


def hide_environment_helpers():
    """
    grid, ground, shadow 같은 환경 표시도 제거.
    """
    # CLO 문서 기준:
    # 0: Light (3D)
    # 1: Light (Render)
    # 2: Wind Controller
    # 3: 3D Shadow
    # 4: Ground Grid
    # 5: Grid
    # 6: All

    hide_options = [
        2,  # Wind Controller
        3,  # 3D Shadow
        4,  # Ground Grid
        5,  # Grid
    ]

    for opt in hide_options:
        safe_call(
            f"SetEnvironmentDisplayProperties({opt}, False)",
            lambda option=opt: utility_api.SetEnvironmentDisplayProperties(option, False)
        )


def prepare_garment_only_render():
    """
    옷만 렌더링하기 위한 최종 render 상태 설정.
    반드시 simulation 이후, render 이전에 호출.
    """
    hide_avatar_for_render()
    hide_unwanted_display_lines()
    hide_environment_helpers()

    try:
        utility_api.Refresh3DWindow()
    except Exception:
        pass

# =============================================================================
# Main
# =============================================================================

def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config_path = args.config or os.environ.get("CLO_DATASET_CONFIG", "") or CONFIG_JSON_PATH
    config_path = os.path.abspath(os.path.expanduser(config_path))
    config = load_config(config_path)
    apply_config(config, args, os.path.dirname(config_path))
    ensure_clo_api()

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(GS_DIR, exist_ok=True)

    if not GARMENT_INPUTS:
        raise RuntimeError("No garment input found. Put .zprj files under output_dir/input/garments, set inputs.garments_dir, or pass --base_zprj.")
    for garment in GARMENT_INPUTS:
        if not os.path.exists(garment["zprj"]):
            raise RuntimeError(f"Garment ZPRJ does not exist: {garment['zprj']}")
    if not os.path.exists(FABRIC_SAMPLE_ROOT):
        raise RuntimeError(f"FABRIC_SAMPLE_ROOT does not exist: {FABRIC_SAMPLE_ROOT}")

    all_sample_dirs = find_sample_folders(FABRIC_SAMPLE_ROOT)

    if len(all_sample_dirs) == 0:
        raise RuntimeError(f"No .zfab sample folders found in {FABRIC_SAMPLE_ROOT}")

    fabric_variants = build_fabric_variant_records(all_sample_dirs)
    validate_fabric_variant_metadata(fabric_variants)
    all_jobs = build_dataset_jobs(GARMENT_INPUTS, fabric_variants)
    jobs = all_jobs[:MAX_SAMPLES] if MAX_SAMPLES > 0 else all_jobs

    print(f"[Info] Found {len(GARMENT_INPUTS)} garment(s)")
    print(f"[Info] Found {len(fabric_variants)} fabric(s)")
    print(f"[Info] Planned {len(all_jobs)} fabric/body sample(s)")
    if MAX_SAMPLES > 0:
        print(f"[Info] Limit CLO processing to {len(jobs)} sample(s)")

    dataset_summary_path = (
        os.path.abspath(DATASET_SUMMARY_JSON)
        if DATASET_SUMMARY_JSON
        else os.path.join(OUT_DIR, "dataset_summary.json")
    )
    os.makedirs(os.path.dirname(dataset_summary_path), exist_ok=True)
    dataset_summary = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "garments": GARMENT_INPUTS,
        "fabric_sample_root": FABRIC_SAMPLE_ROOT,
        "fabric_variants": [
            {
                k: (
                    get_output_fabric_material_json_path(OUT_DIR, item["fabric_id"])
                    if k == "material_json"
                    else v
                )
                for k, v in item.items()
                if k not in ("material_data",)
            }
            for item in fabric_variants
        ],
        "out_dir": OUT_DIR,
        "output_files": {
            "draped_dir": OUT_DIR,
            "gs_dir": GS_DIR,
            "dataset_summary_json": dataset_summary_path,
        },
        "total_available_fabric_variants": len(fabric_variants),
        "total_available_samples": len(all_jobs),
        "num_samples": len(jobs),
        "max_samples": MAX_SAMPLES,
        "stop_on_first_failure": STOP_ON_FIRST_FAILURE,
        "simulation": {
            "steps": SIM_STEPS
        },
        "render": {
            "num_views": NUM_VIEWS,
            "width": IMAGE_WIDTH,
            "height": IMAGE_HEIGHT,
            "start_index": START_INDEX,
            "skip_render": SKIP_RENDER,
        },
        "obj_export": {
            "enabled": EXPORT_OBJ,
            "file_name": OBJ_FILE_NAME,
            "function_candidates": OBJ_EXPORT_FUNCTION_NAMES,
            "include_garment": OBJ_EXPORT_INCLUDE_GARMENT,
            "include_avatar": OBJ_EXPORT_INCLUDE_AVATAR,
            "scale": OBJ_EXPORT_SCALE,
            "export_fabric": True,
            "post_processing": "none",
            "clo_version": CLO_VERSION,
        },
        "samples": []
    }

    output_materials_written = set()

    for sample_idx, job in enumerate(jobs):
        variant = job["fabric_variant"]
        sample_name = job["sample_id"]
        zfab_path = variant["zfab_path"]
        fabric_material_path = get_output_fabric_material_json_path(OUT_DIR, variant["fabric_id"])

        safe_sample_name = safe_name(sample_name)
        out_sample_dir_name = format_stage_template(
            SAMPLE_DIR_TEMPLATE,
            index=sample_idx,
            index1=sample_idx + 1,
            sample_name=safe_sample_name,
            fabric_stem=safe_sample_name,
            garment_id=job["garment_id"],
            fabric_id=variant["fabric_id"],
            bend_id=variant["bend_id"],
            sample_id=safe_sample_name,
        )
        out_sample_dir = os.path.join(OUT_DIR, out_sample_dir_name)
        gs_sample_dir = os.path.join(GS_DIR, out_sample_dir_name)
        out_image_dir = os.path.join(out_sample_dir, "images")
        sample_summary_path = os.path.join(out_sample_dir, SAMPLE_SUMMARY_FILE_NAME)
        planned_draped_zprj_path = os.path.join(out_sample_dir, DRAPED_ZPRJ_FILE_NAME)
        os.makedirs(out_sample_dir, exist_ok=True)
        os.makedirs(gs_sample_dir, exist_ok=True)

        print("=" * 80)
        print(f"[Sample {sample_idx:03d}/{len(jobs)}]")
        print(f"  sample id     : {safe_sample_name}")
        print(f"  garment       : {job['garment_id']}")
        print(f"  garment zprj  : {job['garment_zprj']}")
        print(f"  fabric        : {variant['fabric_id']}")
        print(f"  variant       : {variant['bend_id']}")
        print(f"  source sample : {variant['source_sample_dir']}")
        print(f"  zfab          : {zfab_path}")
        print(f"  output        : {out_sample_dir}")
        print(f"  obj output    : {out_sample_dir}")
        print(f"  3dgs          : {gs_sample_dir}")

        sample_record = {
            "sample_index": sample_idx,
            "sample_id": safe_sample_name,
            "garment_id": job["garment_id"],
            "body_id": job["body_id"],
            "fabric_id": variant["fabric_id"],
            "bend_id": variant["bend_id"],
            "garment_zprj": job["garment_zprj"],
            "source_sample_dir": variant["source_sample_dir"],
            "zfab_path": zfab_path,
            "output_dir": out_sample_dir,
            "output_files": {
                "draped_zprj": planned_draped_zprj_path if SAVE_SIM_ZPRJ else None,
                "obj_dir": out_sample_dir,
                "gs_dir": gs_sample_dir,
                "sample_summary_json": sample_summary_path,
                "material_json": None,
            },
            "status": "started"
        }

        try:
            # 1. base A-pose scene reload
            new_project_and_import_base(job["garment_zprj"])

            # 2. fabric 적용
            added_fabric_idx, pattern_count = add_and_assign_fabric_to_all_patterns(zfab_path)

            # 3. simulation
            simulate_current_scene(SIM_STEPS)

            # 3-1. render 직전에 avatar/표시선 숨김
            if EXPORT_OBJ or not SKIP_RENDER:
                prepare_garment_only_render()

            obj_bundle = None
            if EXPORT_OBJ:
                obj_bundle = export_obj_bundle(out_sample_dir, zfab_path)
                print(f"  [OBJ] {obj_bundle.get('obj_path')}")

            # 4. render
            rendered_images = []
            if not SKIP_RENDER:
                try:
                    rendered_images = export_turntable_images(out_image_dir)
                except Exception as e:
                    print(f"[Warning] Turntable render failed: {e}")
                    print("[Info] Try ExportRenderingImage fallback")
                    rendered_images = export_rendering_image_fallback(out_image_dir)

            # 5. sim result 저장
            sim_zprj_path = None
            if SAVE_SIM_ZPRJ:
                sim_zprj_path = planned_draped_zprj_path
                export_sim_zprj(sim_zprj_path)

            # 6. fabric-level material metadata
            material_dst = fabric_material_path
            material_data = None
            material_json_error = None
            stale_sample_material_path = os.path.join(out_sample_dir, "material.json")
            if os.path.exists(stale_sample_material_path) and os.path.abspath(stale_sample_material_path) != os.path.abspath(material_dst):
                os.remove(stale_sample_material_path)
            material_key = os.path.normcase(os.path.abspath(material_dst))
            if material_key not in output_materials_written:
                try:
                    material_data = build_material_gt_from_zfab(
                        variant["source_sample_dir"],
                        zfab_path,
                        variant["fabric_id"],
                        variant["bend_id"],
                        variant["sample_id"],
                    )
                    os.makedirs(os.path.dirname(material_dst), exist_ok=True)
                    write_json(material_dst, material_data)
                    output_materials_written.add(material_key)
                except Exception as e:
                    material_json_error = str(e)
                    print(f"[Warning] material.json generation failed:\n{material_json_error}")
            if material_data is None and os.path.exists(material_dst):
                material_data, material_json_error = try_read_json(material_dst)
                if material_json_error:
                    print(f"[Warning] material.json parse failed:\n{material_json_error}")

            # 7. sample summary 저장
            sample_record.update({
                "status": "success",
                "added_fabric_index": added_fabric_idx,
                "pattern_count": pattern_count,
                "obj_export": obj_bundle,
                "obj_path": obj_bundle.get("obj_path") if obj_bundle else None,
                "mtl_path": obj_bundle.get("mtl_path") if obj_bundle else None,
                "diffuse_path": obj_bundle.get("diffuse_path") if obj_bundle else None,
                "normal_path": obj_bundle.get("normal_path") if obj_bundle else None,
                "num_rendered_images": len(rendered_images),
                "rendered_images": rendered_images,
                "sim_zprj_path": sim_zprj_path,
                "material_json": material_dst,
                "material_json_error": material_json_error,
                "label_4d": material_data.get("label_4d") if material_data else None,
                "output_files": {
                    "draped_zprj": sim_zprj_path,
                    "obj_dir": out_sample_dir,
                    "gs_dir": gs_sample_dir,
                    "sample_summary_json": sample_summary_path,
                    "material_json": material_dst,
                    "images_dir": out_image_dir if rendered_images else None,
                    "obj": obj_bundle.get("obj_path") if obj_bundle else None,
                    "mtl": obj_bundle.get("mtl_path") if obj_bundle else None,
                    "diffuse": obj_bundle.get("diffuse_path") if obj_bundle else None,
                    "normal": obj_bundle.get("normal_path") if obj_bundle else None,
                },
            })

            write_json(sample_summary_path, sample_record)

            print(f"  [Done] rendered images: {len(rendered_images)}")
            if material_data and "label_4d" in material_data:
                print(f"  label_4d: {material_data['label_4d']}")

        except Exception as e:
            sample_record.update({
                "status": "failed",
                "error": str(e)
            })

            write_json(sample_summary_path, sample_record)

            print(f"  [Failed] {e}")

        dataset_summary["samples"].append(sample_record)

        # 전체 summary 중간 저장
        write_json(dataset_summary_path, dataset_summary)

        if sample_record.get("status") == "failed" and STOP_ON_FIRST_FAILURE:
            dataset_summary["aborted"] = True
            dataset_summary["abort_reason"] = sample_record.get("error", "")
            dataset_summary["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            dataset_summary["num_success"] = len(
                [sample for sample in dataset_summary["samples"] if sample.get("status") == "success"]
            )
            dataset_summary["num_failed"] = len(
                [sample for sample in dataset_summary["samples"] if sample.get("status") == "failed"]
            )
            write_json(dataset_summary_path, dataset_summary)
            print(
                "[Abort] Stopping after first failed sample. "
                "Set clo_simulation.stop_on_first_failure=false to continue through all samples."
            )
            break

    dataset_summary["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    dataset_summary["num_success"] = len(
        [sample for sample in dataset_summary["samples"] if sample.get("status") == "success"]
    )
    dataset_summary["num_failed"] = len(
        [sample for sample in dataset_summary["samples"] if sample.get("status") == "failed"]
    )
    write_json(dataset_summary_path, dataset_summary)

    print("=" * 80)
    print("[Finished]")
    print(f"summary: {dataset_summary_path}")


if __name__ == "__main__":
    main()
