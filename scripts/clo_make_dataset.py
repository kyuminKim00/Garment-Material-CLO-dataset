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
import threading
import zipfile
import ctypes
import ctypes.wintypes

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
FALLBACK_SCRIPT_FILE = r"C:\Users\CGnA\Desktop\CLO\scripts\clo_make_dataset.py"
SCRIPT_FILE = globals().get("__file__", FALLBACK_SCRIPT_FILE)
if not SCRIPT_FILE or str(SCRIPT_FILE).startswith("<") or not os.path.exists(SCRIPT_FILE):
    SCRIPT_FILE = FALLBACK_SCRIPT_FILE
SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(SCRIPT_FILE), ".."))
CONFIG_JSON_PATH = r"C:\Users\CGnA\Desktop\CLO\dataset_config.json"
BASE_ZPRJ_PATH = ""

# 이전 코드로 만든 10개 fabric sample 폴더
# 각 하위 폴더에 .zfab과 material.json이 있다고 가정
FABRIC_SAMPLE_ROOT = os.path.join(SCRIPT_DIR, "bending_zfab_samples")

# simulation/render 결과 저장 위치
OUT_DIR = os.path.join(SCRIPT_DIR, "clo_obj_dataset")
MANUAL_OBJ_DIR = os.path.join(SCRIPT_DIR, "03_manual_obj_exports")
GS_DIR = os.path.join(SCRIPT_DIR, "05_3dgs")
SAMPLE_DIR_TEMPLATE = "{index:03d}_{fabric_stem}"
DRAPED_ZPRJ_FILE_NAME = "draped_garment.zprj"
SAMPLE_SUMMARY_FILE_NAME = "summary.json"
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
EXPORT_OBJ = False
OBJ_FILE_NAME = "obj.obj"
OBJ_EXPORT_FUNCTION_NAMES = [
    "ExportOBJ",
    "ExportOBJW",
]
OBJ_EXPORT_ALLOW_DIALOG = False
OBJ_EXPORT_AUTO_ACCEPT_DIALOG = True
OBJ_EXPORT_DIALOG_TIMEOUT_SEC = 20.0
OBJ_EXPORT_TRY_NULL_OPTION = True
OBJ_EXPORT_USE_IMPORT_EXPORT_OPTION = True
OBJ_EXPORT_INCLUDE_GARMENT = True
OBJ_EXPORT_INCLUDE_AVATAR = False
OBJ_EXPORT_SET_SCALE_IN_OPTION = False
OBJ_EXPORT_SCALE = 1.0
OBJ_EXPORT_SCALE_PERCENT = 100.0
OBJ_POST_EXPORT_SCALE = 0.01
OBJ_NORMALIZE_UV_TO_0_1 = True
OBJ_UV_PADDING = 0.0
OBJ_UV_PRESERVE_ASPECT = True
OBJ_USE_ZFAB_TEXTURES = True
CLO_VERSION = "2026.0.312"


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


def load_config(path):
    if not path:
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


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


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Run CLO simulation and export OBJ bundles.")
    parser.add_argument("--config", default="", help="Pipeline JSON config path.")
    parser.add_argument("--base_zprj", default="", help="Override base .zprj path.")
    parser.add_argument("--fabric_sample_root", default="", help="Override .zfab sample root.")
    parser.add_argument("--out_dir", default="", help="Override CLO output directory.")
    args, _ = parser.parse_known_args(argv)
    return args


def apply_config(config, args):
    global BASE_ZPRJ_PATH, FABRIC_SAMPLE_ROOT, OUT_DIR, MANUAL_OBJ_DIR, GS_DIR
    global SAMPLE_DIR_TEMPLATE, DRAPED_ZPRJ_FILE_NAME, SAMPLE_SUMMARY_FILE_NAME
    global DATASET_SUMMARY_JSON
    global NUM_VIEWS, IMAGE_WIDTH, IMAGE_HEIGHT, START_INDEX
    global SIM_STEPS, SAVE_SIM_ZPRJ, MAX_SAMPLES, STOP_ON_FIRST_FAILURE
    global SKIP_RENDER, EXPORT_OBJ
    global OBJ_FILE_NAME, OBJ_EXPORT_FUNCTION_NAMES, OBJ_EXPORT_ALLOW_DIALOG
    global OBJ_EXPORT_AUTO_ACCEPT_DIALOG, OBJ_EXPORT_DIALOG_TIMEOUT_SEC
    global OBJ_EXPORT_TRY_NULL_OPTION
    global OBJ_EXPORT_USE_IMPORT_EXPORT_OPTION, OBJ_EXPORT_INCLUDE_GARMENT
    global OBJ_EXPORT_INCLUDE_AVATAR, OBJ_EXPORT_SCALE, OBJ_EXPORT_SCALE_PERCENT
    global OBJ_EXPORT_SET_SCALE_IN_OPTION, OBJ_POST_EXPORT_SCALE
    global OBJ_NORMALIZE_UV_TO_0_1, OBJ_UV_PADDING, OBJ_UV_PRESERVE_ASPECT
    global OBJ_USE_ZFAB_TEXTURES
    global CLO_VERSION

    output_root = (
        deep_get(config, ["project", "output_dir"])
        or deep_get(config, ["project", "dataset_root"])
        or deep_get(config, ["paths", "output_dir"])
        or deep_get(config, ["paths", "dataset_root"])
        or deep_get(config, ["paths", "root_dir"])
        or ""
    )
    output_root = os.path.abspath(os.path.expanduser(output_root)) if output_root else ""

    BASE_ZPRJ_PATH = (
        args.base_zprj
        or deep_get(config, ["inputs", "base_garment_zprj"])
        or deep_get(config, ["stage_2_clo_simulation", "inputs", "base_model_zprj"])
        or deep_get(config, ["clo", "base_zprj"])
        or deep_get(config, ["paths", "base_zprj"])
        or find_input_file(output_root, "zprj", "base zprj")
        or BASE_ZPRJ_PATH
    )
    FABRIC_SAMPLE_ROOT = (
        args.fabric_sample_root
        or deep_get(config, ["stage_2_clo_simulation", "inputs", "fabric_dir"])
        or deep_get(config, ["stage_1_fabric_sampler", "outputs", "fabric_dir"])
        or deep_get(config, ["clo", "fabric_sample_root"])
        or deep_get(config, ["paths", "zfab_output_dir"])
        or (os.path.join(output_root, deep_get(config, ["naming", "fabric_dir"], "01_fabric_bending")) if output_root else "")
        or (os.path.join(output_root, "bending_zfab_samples") if output_root else "")
        or FABRIC_SAMPLE_ROOT
    )
    OUT_DIR = (
        args.out_dir
        or deep_get(config, ["stage_2_clo_simulation", "outputs", "draped_dir"])
        or deep_get(config, ["clo", "output_dir"])
        or deep_get(config, ["paths", "clo_output_dir"])
        or (os.path.join(output_root, deep_get(config, ["naming", "draped_dir"], "02_draped_garments")) if output_root else "")
        or (os.path.join(output_root, "clo_obj_dataset") if output_root else "")
        or OUT_DIR
    )
    MANUAL_OBJ_DIR = (
        deep_get(config, ["stage_3_manual_obj_export", "outputs", "manual_obj_dir"])
        or deep_get(config, ["manual_obj_export", "output_dir"])
        or (os.path.join(output_root, deep_get(config, ["naming", "manual_obj_dir"], "03_manual_obj_exports")) if output_root else "")
        or MANUAL_OBJ_DIR
    )
    GS_DIR = (
        deep_get(config, ["stage_5_3dgs_training", "outputs", "gs_dir"])
        or deep_get(config, ["3dgs_training", "output_dir"])
        or (os.path.join(output_root, deep_get(config, ["naming", "gs_dir"], "05_3dgs")) if output_root else "")
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
    SAVE_SIM_ZPRJ = bool(
        deep_get(
            config,
            ["stage_2_clo_simulation", "settings", "save_sim_zprj"],
            deep_get(config, ["clo_simulation", "save_sim_zprj"], deep_get(config, ["clo", "save_sim_zprj"], SAVE_SIM_ZPRJ)),
        )
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
    OBJ_FILE_NAME = str(deep_get(config, ["clo", "obj_file_name"], OBJ_FILE_NAME))
    OBJ_EXPORT_FUNCTION_NAMES = list(
        deep_get(config, ["clo", "obj_export_function_names"], OBJ_EXPORT_FUNCTION_NAMES)
    )
    OBJ_EXPORT_ALLOW_DIALOG = bool(
        deep_get(config, ["clo", "obj_export_allow_dialog"], OBJ_EXPORT_ALLOW_DIALOG)
    )
    OBJ_EXPORT_AUTO_ACCEPT_DIALOG = bool(
        deep_get(config, ["clo", "obj_export_auto_accept_dialog"], OBJ_EXPORT_AUTO_ACCEPT_DIALOG)
    )
    OBJ_EXPORT_DIALOG_TIMEOUT_SEC = float(
        deep_get(config, ["clo", "obj_export_dialog_timeout_sec"], OBJ_EXPORT_DIALOG_TIMEOUT_SEC)
    )
    OBJ_EXPORT_TRY_NULL_OPTION = bool(
        deep_get(config, ["clo", "obj_export_try_null_option"], OBJ_EXPORT_TRY_NULL_OPTION)
    )
    OBJ_EXPORT_USE_IMPORT_EXPORT_OPTION = bool(
        deep_get(
            config,
            ["clo", "obj_export_use_import_export_option"],
            OBJ_EXPORT_USE_IMPORT_EXPORT_OPTION,
        )
    )
    OBJ_EXPORT_INCLUDE_GARMENT = bool(
        deep_get(config, ["clo", "obj_export_include_garment"], OBJ_EXPORT_INCLUDE_GARMENT)
    )
    OBJ_EXPORT_INCLUDE_AVATAR = bool(
        deep_get(config, ["clo", "obj_export_include_avatar"], OBJ_EXPORT_INCLUDE_AVATAR)
    )
    OBJ_EXPORT_SET_SCALE_IN_OPTION = bool(
        deep_get(
            config,
            ["clo", "obj_export_set_scale_in_option"],
            OBJ_EXPORT_SET_SCALE_IN_OPTION,
        )
    )
    OBJ_EXPORT_SCALE = float(deep_get(config, ["clo", "obj_export_scale"], OBJ_EXPORT_SCALE))
    OBJ_EXPORT_SCALE_PERCENT = float(
        deep_get(config, ["clo", "obj_export_scale_percent"], OBJ_EXPORT_SCALE_PERCENT)
    )
    OBJ_POST_EXPORT_SCALE = float(
        deep_get(config, ["clo", "obj_post_export_scale"], OBJ_POST_EXPORT_SCALE)
    )
    OBJ_NORMALIZE_UV_TO_0_1 = bool(
        deep_get(config, ["clo", "obj_normalize_uv_to_0_1"], OBJ_NORMALIZE_UV_TO_0_1)
    )
    OBJ_UV_PADDING = float(deep_get(config, ["clo", "obj_uv_padding"], OBJ_UV_PADDING))
    OBJ_UV_PRESERVE_ASPECT = bool(
        deep_get(config, ["clo", "obj_uv_preserve_aspect"], OBJ_UV_PRESERVE_ASPECT)
    )
    OBJ_USE_ZFAB_TEXTURES = bool(
        deep_get(config, ["clo", "obj_use_zfab_textures"], OBJ_USE_ZFAB_TEXTURES)
    )
    CLO_VERSION = str(deep_get(config, ["clo", "clo_version"], CLO_VERSION))


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


def get_material_json_path(sample_dir):
    if os.path.isfile(sample_dir) and sample_dir.lower().endswith(".zfab"):
        base, _ = os.path.splitext(sample_dir)
        candidates = [
            base + ".material.json",
            base + ".json",
            os.path.join(
                os.path.dirname(sample_dir),
                "material_json",
                os.path.basename(base) + ".material.json",
            ),
            os.path.join(
                os.path.dirname(sample_dir),
                "material_json",
                os.path.basename(base) + ".json",
            ),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    path = os.path.join(sample_dir, "material.json")
    if os.path.exists(path):
        return path
    return None


# =============================================================================
# CLO wrappers
# =============================================================================

def new_project_and_import_base():
    """
    매 sample마다 base ZPRJ를 다시 열어 drape 초기 상태를 동일하게 만듦.
    """
    try:
        utility_api.NewProject()
    except Exception as e:
        print(f"[Warning] NewProject failed or unavailable: {e}")

    result = import_api.ImportFile(BASE_ZPRJ_PATH)

    # CLO API는 성공 시 None/string/bool 등 버전별로 다를 수 있음
    if result == "" or result is False:
        raise RuntimeError(f"Import base ZPRJ failed: {BASE_ZPRJ_PATH}")

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


def find_import_export_option_class():
    modules = [export_api, import_api, utility_api]
    for module_name in ["CLOAPIInterface", "Marvelous", "marvelous"]:
        try:
            modules.append(__import__(module_name))
        except Exception:
            pass
    modules.extend(list(sys.modules.values()))

    class_names = [
        "ImportExportOption",
        "ImportExportOptions",
        "CLOImportExportOption",
    ]
    seen = set()
    for module in modules:
        if module is None:
            continue
        module_id = id(module)
        if module_id in seen:
            continue
        seen.add(module_id)
        for class_name in class_names:
            cls = getattr(module, class_name, None)
            if callable(cls):
                return cls
        try:
            names = [name for name in dir(module) if not name.startswith("__")]
        except Exception:
            continue
        for name in names:
            lower_name = name.lower()
            if "import" not in lower_name or "export" not in lower_name or "option" not in lower_name:
                continue
            cls = getattr(module, name, None)
            if callable(cls):
                return cls
    return None


def try_set_option_value(option, names, value, option_log):
    for name in names:
        try:
            setattr(option, name, value)
            option_log["set"].append({"name": name, "value": value})
        except Exception as e:
            option_log["failed"].append({"name": name, "value": value, "error": repr(e)})


def make_obj_export_option():
    cls = find_import_export_option_class()
    option_log = {
        "class": repr(cls),
        "dir": [],
        "set": [],
        "failed": [],
        "requested": {
            "clo_version": CLO_VERSION,
            "include_garment": OBJ_EXPORT_INCLUDE_GARMENT,
            "include_avatar": OBJ_EXPORT_INCLUDE_AVATAR,
            "set_scale_in_option": OBJ_EXPORT_SET_SCALE_IN_OPTION,
            "scale": OBJ_EXPORT_SCALE,
            "scale_percent": OBJ_EXPORT_SCALE_PERCENT,
            "post_export_scale": OBJ_POST_EXPORT_SCALE,
            "normalize_uv_to_0_1": OBJ_NORMALIZE_UV_TO_0_1,
            "uv_padding": OBJ_UV_PADDING,
            "uv_preserve_aspect": OBJ_UV_PRESERVE_ASPECT,
            "use_zfab_textures": OBJ_USE_ZFAB_TEXTURES,
            "allow_dialog": OBJ_EXPORT_ALLOW_DIALOG,
            "auto_accept_dialog": OBJ_EXPORT_AUTO_ACCEPT_DIALOG,
            "dialog_timeout_sec": OBJ_EXPORT_DIALOG_TIMEOUT_SEC,
            "try_null_option": OBJ_EXPORT_TRY_NULL_OPTION,
        },
    }
    if cls is None:
        option_log["error"] = "ImportExportOption class was not found."
        return None, option_log

    try:
        option = cls()
    except Exception as e:
        option_log["error"] = f"ImportExportOption constructor failed: {repr(e)}"
        return None, option_log

    try:
        option_log["dir"] = [name for name in dir(option) if not name.startswith("__")]
    except Exception:
        pass

    try_set_option_value(option, [
        "bExportGarment",
        "exportGarment",
        "ExportGarment",
        "bGarment",
        "garment",
        "includeGarment",
        "bIncludeGarment",
        "bSaveGarment",
        "m_bExportGarment",
    ], OBJ_EXPORT_INCLUDE_GARMENT, option_log)

    try_set_option_value(option, [
        "bExportAvatar",
        "exportAvatar",
        "ExportAvatar",
        "bAvatar",
        "avatar",
        "includeAvatar",
        "bIncludeAvatar",
        "bSaveAvatar",
        "bExportAvatarMesh",
        "m_bExportAvatar",
    ], OBJ_EXPORT_INCLUDE_AVATAR, option_log)

    try_set_option_value(option, [
        "bShowDialog",
        "showDialog",
        "bUseDialog",
        "useDialog",
        "bWithDialog",
        "withDialog",
        "dialog",
        "m_bShowDialog",
    ], OBJ_EXPORT_ALLOW_DIALOG, option_log)

    if OBJ_EXPORT_SET_SCALE_IN_OPTION:
        try_set_option_value(option, [
            "scale",
            "Scale",
            "fScale",
            "dScale",
            "objScale",
            "fObjScale",
            "exportScale",
            "fExportScale",
            "m_fScale",
            "m_dScale",
        ], OBJ_EXPORT_SCALE, option_log)

        try_set_option_value(option, [
            "scalePercent",
            "ScalePercent",
            "fScalePercent",
            "dScalePercent",
            "size",
            "Size",
            "sizePercent",
            "SizePercent",
            "fSizePercent",
            "dSizePercent",
            "exportSize",
            "fExportSize",
            "m_fScalePercent",
        ], OBJ_EXPORT_SCALE_PERCENT, option_log)

    try_set_option_value(option, [
        "bExportTexture",
        "exportTexture",
        "bTexture",
        "texture",
        "bSaveTexture",
        "saveTexture",
        "bCreateTextureFolder",
    ], True, option_log)

    return option, option_log


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


def is_image_entry(name):
    lower = name.lower()
    return lower.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff"))


def rank_zfab_texture_entry(entry_name, role):
    if not is_image_entry(entry_name):
        return None

    name = os.path.basename(entry_name).lower()
    if role == "diffuse":
        reject_tokens = ["normal", "nrm", "rough", "disp", "metal", "mtl", "opacity", "alpha"]
        if any(token in name for token in reject_tokens):
            return None
        token_groups = [
            ["base_rgb"],
            ["basecolor", "base_color", "base color"],
            ["diffuse", "albedo"],
            ["rgb"],
            ["base"],
        ]
    elif role == "normal":
        reject_tokens = ["rough", "disp", "metal", "mtl", "opacity", "alpha"]
        if any(token in name for token in reject_tokens):
            return None
        token_groups = [
            ["normal"],
            ["nrm"],
        ]
    else:
        return None

    for group_idx, tokens in enumerate(token_groups):
        for token in tokens:
            if token in name:
                return (group_idx, len(name), name)
    return None


def find_zfab_texture_entry(entries, role):
    candidates = []
    for entry in entries:
        rank = rank_zfab_texture_entry(entry.filename, role)
        if rank is not None:
            candidates.append((rank, entry))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def extract_zfab_texture_entry(zfab_file, entry, out_sample_dir, dst_base_name):
    if entry is None:
        return None
    ext = os.path.splitext(entry.filename)[1].lower() or ".png"
    dst_path = os.path.join(out_sample_dir, dst_base_name + ext)
    with zfab_file.open(entry, "r") as src, open(dst_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return os.path.abspath(dst_path)


def mtl_texture_ref(texture_path, mtl_dir):
    ref = os.path.relpath(texture_path, mtl_dir)
    return ref.replace(os.sep, "/")


def rewrite_mtl_texture_paths(mtl_path, diffuse_path=None, normal_path=None):
    if not mtl_path or not os.path.exists(mtl_path):
        return {
            "updated": False,
            "reason": "mtl not found",
        }

    mtl_dir = os.path.dirname(mtl_path)
    tmp_path = mtl_path + ".texture_tmp"
    updates = []

    with open(mtl_path, "r", encoding="utf-8-sig", errors="ignore") as src, open(
        tmp_path, "w", encoding="utf-8", newline=""
    ) as dst:
        for raw_line in src:
            stripped = raw_line.rstrip("\n\r")
            newline = raw_line[len(stripped):]
            parts = stripped.split()
            if parts:
                key = parts[0].lower()
                if diffuse_path and key in ("map_ka", "map_kd", "map_basecolor", "map_albedo"):
                    ref = mtl_texture_ref(diffuse_path, mtl_dir)
                    dst.write(f"{parts[0]} {ref}{newline or os.linesep}")
                    updates.append({"key": parts[0], "path": diffuse_path})
                    continue
                if normal_path and key in ("map_bump", "bump", "map_normal", "norm", "map_norm"):
                    ref = mtl_texture_ref(normal_path, mtl_dir)
                    dst.write(f"{parts[0]} {ref}{newline or os.linesep}")
                    updates.append({"key": parts[0], "path": normal_path})
                    continue
            dst.write(raw_line)

    os.replace(tmp_path, mtl_path)
    return {
        "updated": bool(updates),
        "updates": updates,
    }


def replace_obj_bundle_textures_from_zfab(bundle, zfab_path, out_sample_dir):
    log = {
        "enabled": bool(OBJ_USE_ZFAB_TEXTURES),
        "zfab_path": zfab_path,
        "diffuse_entry": None,
        "normal_entry": None,
        "extracted_diffuse_path": None,
        "extracted_normal_path": None,
        "mtl_rewrite": None,
    }
    if not OBJ_USE_ZFAB_TEXTURES:
        log["reason"] = "disabled"
        return log
    if not zfab_path or not os.path.exists(zfab_path):
        log["reason"] = "zfab not found"
        return log
    if not zipfile.is_zipfile(zfab_path):
        log["reason"] = "zfab is not a zip file"
        return log

    with zipfile.ZipFile(zfab_path, "r") as zfab_file:
        entries = zfab_file.infolist()
        diffuse_entry = find_zfab_texture_entry(entries, "diffuse")
        normal_entry = find_zfab_texture_entry(entries, "normal")
        log["diffuse_entry"] = diffuse_entry.filename if diffuse_entry else None
        log["normal_entry"] = normal_entry.filename if normal_entry else None

        diffuse_path = extract_zfab_texture_entry(
            zfab_file, diffuse_entry, out_sample_dir, "fabric_diffuse"
        )
        normal_path = extract_zfab_texture_entry(
            zfab_file, normal_entry, out_sample_dir, "fabric_normal"
        )

    log["extracted_diffuse_path"] = diffuse_path
    log["extracted_normal_path"] = normal_path

    if diffuse_path:
        bundle["diffuse_path"] = diffuse_path
    if normal_path:
        bundle["normal_path"] = normal_path

    if bundle.get("mtl_path"):
        log["mtl_rewrite"] = rewrite_mtl_texture_paths(
            bundle.get("mtl_path"),
            diffuse_path,
            normal_path,
        )

    for path in (diffuse_path, normal_path):
        if path and path not in bundle["files"]:
            bundle["files"].append(path)

    return log


def get_window_text(hwnd):
    if os.name != "nt":
        return ""
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def get_window_class_name(hwnd):
    if os.name != "nt":
        return ""
    user32 = ctypes.windll.user32
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def get_window_pid(hwnd):
    if os.name != "nt":
        return 0
    user32 = ctypes.windll.user32
    window_pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
    return int(window_pid.value)


def enum_child_window_texts(hwnd):
    if os.name != "nt":
        return []

    user32 = ctypes.windll.user32
    texts = []

    enum_proc_type = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM,
    )

    def callback(child_hwnd, lparam):
        text = get_window_text(child_hwnd)
        class_name = get_window_class_name(child_hwnd)
        if text or class_name:
            texts.append((child_hwnd, text, class_name))
        return True

    user32.EnumChildWindows(hwnd, enum_proc_type(callback), 0)
    return texts


def get_dialog_control_id(hwnd):
    if os.name != "nt":
        return 0
    try:
        return int(ctypes.windll.user32.GetDlgCtrlID(hwnd))
    except Exception:
        return 0


def is_ok_button_text(text):
    value = (text or "").strip().lower().replace("&", "")
    return value == "ok"


def is_ok_button(hwnd, text, class_name):
    if (class_name or "").lower() != "button":
        return False
    return is_ok_button_text(text) or get_dialog_control_id(hwnd) == 1


def is_likely_obj_export_dialog(hwnd, current_pid, foreground_hwnd):
    if os.name != "nt":
        return False

    user32 = ctypes.windll.user32
    if not user32.IsWindowVisible(hwnd):
        return False

    title = get_window_text(hwnd)
    class_name = get_window_class_name(hwnd)
    pid = get_window_pid(hwnd)
    child_texts = enum_child_window_texts(hwnd)
    text_blob = " ".join([title, class_name] + [text for _, text, _ in child_texts])
    lower_blob = text_blob.lower()

    ok_children = [
        child_hwnd
        for child_hwnd, text, child_class in child_texts
        if is_ok_button(child_hwnd, text, child_class)
    ]
    has_ok = len(ok_children) > 0

    export_tokens = [
        "obj",
        "export",
        "save",
        "option",
        "options",
        "garment",
        "avatar",
        "texture",
        "scale",
    ]
    has_export_hint = any(token in lower_blob for token in export_tokens)
    same_process = current_pid > 0 and pid == current_pid
    is_dialog_class = class_name == "#32770"
    is_foreground_dialog = foreground_hwnd and int(hwnd) == int(foreground_hwnd) and is_dialog_class

    return has_ok and (
        has_export_hint
        or (same_process and is_dialog_class)
        or is_foreground_dialog
    )


def find_obj_export_dialog_windows():
    if os.name != "nt":
        return []

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    current_pid = kernel32.GetCurrentProcessId()
    foreground_hwnd = user32.GetForegroundWindow()
    windows = []

    enum_proc_type = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM,
    )

    def callback(hwnd, lparam):
        if is_likely_obj_export_dialog(hwnd, current_pid, foreground_hwnd):
            title = get_window_text(hwnd)
            class_name = get_window_class_name(hwnd)
            windows.append((hwnd, title, class_name))
        return True

    user32.EnumWindows(enum_proc_type(callback), 0)
    return windows


def post_ok_to_window(hwnd):
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    wm_command = 0x0111
    wm_keydown = 0x0100
    wm_keyup = 0x0101
    bm_click = 0x00F5
    id_ok = 1
    vk_return = 0x0D
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    for child_hwnd, text, class_name in enum_child_window_texts(hwnd):
        if is_ok_button(child_hwnd, text, class_name):
            try:
                user32.SendMessageW(child_hwnd, bm_click, 0, 0)
            except Exception:
                pass
    user32.PostMessageW(hwnd, wm_command, id_ok, 0)
    user32.PostMessageW(hwnd, wm_keydown, vk_return, 0)
    user32.PostMessageW(hwnd, wm_keyup, vk_return, 0)


def start_obj_export_dialog_auto_accept(signature_name):
    log = {
        "enabled": bool(OBJ_EXPORT_AUTO_ACCEPT_DIALOG),
        "signature": signature_name,
        "timeout_sec": OBJ_EXPORT_DIALOG_TIMEOUT_SEC,
        "windows": [],
    }
    if not OBJ_EXPORT_AUTO_ACCEPT_DIALOG or os.name != "nt":
        return None, log

    stop_event = threading.Event()

    def worker():
        deadline = time.time() + OBJ_EXPORT_DIALOG_TIMEOUT_SEC
        while not stop_event.is_set() and time.time() < deadline:
            for hwnd, title, class_name in find_obj_export_dialog_windows():
                record = {
                    "title": title,
                    "class_name": class_name,
                    "hwnd": int(hwnd),
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                log["windows"].append(record)
                post_ok_to_window(hwnd)
            time.sleep(0.2)
        log["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    thread = threading.Thread(target=worker, name="clo_obj_export_dialog_auto_accept")
    thread.daemon = True
    thread.start()
    return (stop_event, thread), log


def make_dialog_export_call(func, out_obj_path, signature_name):
    def call():
        worker_state, dialog_log = start_obj_export_dialog_auto_accept(signature_name)
        call.dialog_log = dialog_log
        try:
            return func(out_obj_path)
        finally:
            if worker_state is not None:
                stop_event, thread = worker_state
                stop_event.set()
                thread.join(1.0)
    call.dialog_log = {}
    return call


def call_obj_export(func, out_obj_path, option):
    # CLO 2026 exposes ExportOBJ(path, ImportExportOption). The bare
    # ExportOBJ(path) overload opens the OBJ export dialog, so it is disabled
    # unless OBJ_EXPORT_ALLOW_DIALOG is explicitly enabled.
    candidates = []
    if OBJ_EXPORT_USE_IMPORT_EXPORT_OPTION and option is not None:
        candidates.extend([
            ("path_import_export_option", lambda: func(out_obj_path, option)),
        ])
    if OBJ_EXPORT_USE_IMPORT_EXPORT_OPTION and option is None and OBJ_EXPORT_TRY_NULL_OPTION:
        candidates.extend([
            ("path_null_import_export_option", lambda: func(out_obj_path, None)),
        ])
    if OBJ_EXPORT_ALLOW_DIALOG or OBJ_EXPORT_AUTO_ACCEPT_DIALOG:
        signature_name = "path_dialog_auto_accept" if OBJ_EXPORT_AUTO_ACCEPT_DIALOG else "path_dialog_allowed"
        candidates.append((signature_name, make_dialog_export_call(func, out_obj_path, signature_name)))
    return candidates


def scale_obj_vertices(obj_path, scale):
    if not obj_path or not os.path.exists(obj_path):
        return None
    if scale == 1.0:
        return {
            "applied": False,
            "scale": scale,
            "reason": "scale is 1.0",
        }

    tmp_path = obj_path + ".scaled_tmp"
    vertex_count = 0
    with open(obj_path, "r", encoding="utf-8-sig", errors="ignore") as src, open(
        tmp_path, "w", encoding="utf-8", newline=""
    ) as dst:
        for line in src:
            if line.startswith("v "):
                parts = line.rstrip("\n\r").split()
                if len(parts) >= 4:
                    try:
                        x = float(parts[1]) * scale
                        y = float(parts[2]) * scale
                        z = float(parts[3]) * scale
                        rest = " ".join(parts[4:])
                        suffix = f" {rest}" if rest else ""
                        dst.write(f"v {x:.9f} {y:.9f} {z:.9f}{suffix}\n")
                        vertex_count += 1
                        continue
                    except Exception:
                        pass
            dst.write(line)

    os.replace(tmp_path, obj_path)
    return {
        "applied": True,
        "scale": scale,
        "vertex_count": vertex_count,
    }


def normalize_obj_uv_coordinates(obj_path, enabled=True, padding=0.0, preserve_aspect=True):
    if not enabled:
        return {
            "applied": False,
            "reason": "disabled",
        }
    if not obj_path or not os.path.exists(obj_path):
        return None

    padding = max(0.0, min(float(padding), 0.49))
    uv_values = []
    with open(obj_path, "r", encoding="utf-8-sig", errors="ignore") as f:
        lines = f.readlines()

    for line in lines:
        if not line.startswith("vt "):
            continue
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        try:
            uv_values.append((float(parts[1]), float(parts[2])))
        except Exception:
            pass

    if not uv_values:
        return {
            "applied": False,
            "reason": "no vt coordinates",
        }

    min_u = min(u for u, _ in uv_values)
    max_u = max(u for u, _ in uv_values)
    min_v = min(v for _, v in uv_values)
    max_v = max(v for _, v in uv_values)
    span_u = max_u - min_u
    span_v = max_v - min_v
    available = 1.0 - (padding * 2.0)

    if span_u <= 0.0 and span_v <= 0.0:
        return {
            "applied": False,
            "reason": "degenerate uv bounds",
            "before": {
                "min_u": min_u,
                "max_u": max_u,
                "min_v": min_v,
                "max_v": max_v,
            },
        }

    if preserve_aspect:
        max_span = max(span_u, span_v)
        scale_u = available / max_span if max_span > 0.0 else 1.0
        scale_v = scale_u
        used_u = span_u * scale_u
        used_v = span_v * scale_v
        offset_u = padding + ((available - used_u) * 0.5) - (min_u * scale_u)
        offset_v = padding + ((available - used_v) * 0.5) - (min_v * scale_v)
    else:
        scale_u = available / span_u if span_u > 0.0 else 1.0
        scale_v = available / span_v if span_v > 0.0 else 1.0
        offset_u = padding - (min_u * scale_u)
        offset_v = padding - (min_v * scale_v)

    tmp_path = obj_path + ".uv_tmp"
    vt_count = 0
    after_min_u = None
    after_max_u = None
    after_min_v = None
    after_max_v = None

    with open(tmp_path, "w", encoding="utf-8", newline="") as dst:
        for line in lines:
            if line.startswith("vt "):
                stripped = line.rstrip("\n\r")
                newline = line[len(stripped):]
                parts = stripped.split()
                if len(parts) >= 3:
                    try:
                        u = (float(parts[1]) * scale_u) + offset_u
                        v = (float(parts[2]) * scale_v) + offset_v
                        rest = " ".join(parts[3:])
                        suffix = f" {rest}" if rest else ""
                        dst.write(f"vt {u:.9f} {v:.9f}{suffix}{newline or os.linesep}")
                        vt_count += 1
                        after_min_u = u if after_min_u is None else min(after_min_u, u)
                        after_max_u = u if after_max_u is None else max(after_max_u, u)
                        after_min_v = v if after_min_v is None else min(after_min_v, v)
                        after_max_v = v if after_max_v is None else max(after_max_v, v)
                        continue
                    except Exception:
                        pass
            dst.write(line)

    os.replace(tmp_path, obj_path)
    return {
        "applied": True,
        "padding": padding,
        "preserve_aspect": bool(preserve_aspect),
        "vt_count": vt_count,
        "before": {
            "min_u": min_u,
            "max_u": max_u,
            "min_v": min_v,
            "max_v": max_v,
            "span_u": span_u,
            "span_v": span_v,
        },
        "after": {
            "min_u": after_min_u,
            "max_u": after_max_u,
            "min_v": after_min_v,
            "max_v": after_max_v,
        },
        "scale_u": scale_u,
        "scale_v": scale_v,
        "offset_u": offset_u,
        "offset_v": offset_v,
    }


def export_obj_bundle(out_sample_dir, zfab_path=None):
    os.makedirs(out_sample_dir, exist_ok=True)
    out_obj_path = os.path.abspath(os.path.join(out_sample_dir, OBJ_FILE_NAME))
    attempts = []
    option, option_log = make_obj_export_option()

    for func_name in OBJ_EXPORT_FUNCTION_NAMES:
        func = getattr(export_api, func_name, None)
        if not callable(func):
            attempts.append({
                "function": func_name,
                "status": "missing",
            })
            continue

        for signature_name, call in call_obj_export(func, out_obj_path, option):
            try:
                result = call()
                bundle = collect_obj_bundle(out_sample_dir, out_obj_path)
                attempts.append({
                    "function": func_name,
                    "signature": signature_name,
                    "status": "called",
                    "result": str(result),
                    "obj_exists": bool(bundle["obj_path"]),
                    "dialog_auto_accept": getattr(call, "dialog_log", {}),
                })
                if bundle["obj_path"]:
                    zfab_texture_log = replace_obj_bundle_textures_from_zfab(
                        bundle,
                        zfab_path,
                        out_sample_dir,
                    )
                    uv_result = normalize_obj_uv_coordinates(
                        bundle["obj_path"],
                        OBJ_NORMALIZE_UV_TO_0_1,
                        OBJ_UV_PADDING,
                        OBJ_UV_PRESERVE_ASPECT,
                    )
                    scale_result = scale_obj_vertices(bundle["obj_path"], OBJ_POST_EXPORT_SCALE)
                    success_option_log = option_log
                    if signature_name == "path_dialog_auto_accept":
                        success_option_log = {
                            "used": False,
                            "fallback": "ExportOBJ(path) with automatic dialog accept",
                        }
                    bundle.update({
                        "export_function": func_name,
                        "export_signature": signature_name,
                        "raw_result": str(result),
                        "import_export_option": success_option_log,
                        "dialog_auto_accept": getattr(call, "dialog_log", {}),
                        "zfab_textures": zfab_texture_log,
                        "post_export_uv": uv_result,
                        "post_export_scale": scale_result,
                    })
                    return bundle
            except Exception as e:
                attempts.append({
                    "function": func_name,
                    "signature": signature_name,
                    "status": "failed",
                    "error": repr(e),
                    "dialog_auto_accept": getattr(call, "dialog_log", {}),
                })

    error_record = {
        "requested_obj_path": out_obj_path,
        "attempts": attempts,
        "import_export_option": option_log,
        "available_export_api_functions": export_api_function_names(),
        "available_export_api_function_details": export_api_function_details(),
        "api_module_symbol_details": api_module_symbol_details(),
        "allow_dialog": OBJ_EXPORT_ALLOW_DIALOG,
        "auto_accept_dialog": OBJ_EXPORT_AUTO_ACCEPT_DIALOG,
        "try_null_option": OBJ_EXPORT_TRY_NULL_OPTION,
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
    default_config = os.path.join(os.path.dirname(SCRIPT_FILE), "dataset_pipeline_config.json")
    config_path = CONFIG_JSON_PATH or args.config or os.environ.get("CLO_DATASET_CONFIG", "")
    if not config_path and os.path.exists(default_config):
        config_path = default_config
    config = load_config(config_path)
    apply_config(config, args)
    ensure_clo_api()

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(MANUAL_OBJ_DIR, exist_ok=True)
    os.makedirs(GS_DIR, exist_ok=True)

    if not BASE_ZPRJ_PATH:
        raise RuntimeError("BASE_ZPRJ_PATH is empty. Set inputs.base_garment_zprj in the config, or pass --base_zprj.")
    if not os.path.exists(BASE_ZPRJ_PATH):
        raise RuntimeError(f"BASE_ZPRJ_PATH does not exist: {BASE_ZPRJ_PATH}")
    if not os.path.exists(FABRIC_SAMPLE_ROOT):
        raise RuntimeError(f"FABRIC_SAMPLE_ROOT does not exist: {FABRIC_SAMPLE_ROOT}")

    all_sample_dirs = find_sample_folders(FABRIC_SAMPLE_ROOT)

    if len(all_sample_dirs) == 0:
        raise RuntimeError(f"No .zfab sample folders found in {FABRIC_SAMPLE_ROOT}")

    sample_dirs = all_sample_dirs[:MAX_SAMPLES] if MAX_SAMPLES > 0 else all_sample_dirs

    print(f"[Info] Found {len(all_sample_dirs)} fabric samples")
    if MAX_SAMPLES > 0:
        print(f"[Info] Limit CLO processing to {len(sample_dirs)} sample(s)")

    dataset_summary_path = (
        os.path.abspath(DATASET_SUMMARY_JSON)
        if DATASET_SUMMARY_JSON
        else os.path.join(OUT_DIR, "dataset_summary.json")
    )
    os.makedirs(os.path.dirname(dataset_summary_path), exist_ok=True)
    dataset_summary = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_zprj": BASE_ZPRJ_PATH,
        "fabric_sample_root": FABRIC_SAMPLE_ROOT,
        "out_dir": OUT_DIR,
        "output_files": {
            "draped_dir": OUT_DIR,
            "manual_obj_dir": MANUAL_OBJ_DIR,
            "gs_dir": GS_DIR,
            "dataset_summary_json": dataset_summary_path,
        },
        "total_available_samples": len(all_sample_dirs),
        "num_samples": len(sample_dirs),
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
            "allow_dialog": OBJ_EXPORT_ALLOW_DIALOG,
            "auto_accept_dialog": OBJ_EXPORT_AUTO_ACCEPT_DIALOG,
            "dialog_timeout_sec": OBJ_EXPORT_DIALOG_TIMEOUT_SEC,
            "try_null_option": OBJ_EXPORT_TRY_NULL_OPTION,
            "use_import_export_option": OBJ_EXPORT_USE_IMPORT_EXPORT_OPTION,
            "include_garment": OBJ_EXPORT_INCLUDE_GARMENT,
            "include_avatar": OBJ_EXPORT_INCLUDE_AVATAR,
            "set_scale_in_option": OBJ_EXPORT_SET_SCALE_IN_OPTION,
            "scale": OBJ_EXPORT_SCALE,
            "scale_percent": OBJ_EXPORT_SCALE_PERCENT,
            "post_export_scale": OBJ_POST_EXPORT_SCALE,
            "normalize_uv_to_0_1": OBJ_NORMALIZE_UV_TO_0_1,
            "uv_padding": OBJ_UV_PADDING,
            "uv_preserve_aspect": OBJ_UV_PRESERVE_ASPECT,
            "use_zfab_textures": OBJ_USE_ZFAB_TEXTURES,
            "clo_version": CLO_VERSION,
        },
        "samples": []
    }

    for sample_idx, sample_dir in enumerate(sample_dirs):
        sample_name = os.path.splitext(os.path.basename(sample_dir))[0] if os.path.isfile(sample_dir) else os.path.basename(sample_dir)
        zfab_path = get_zfab_path(sample_dir)
        material_src = get_material_json_path(sample_dir)

        safe_sample_name = safe_name(sample_name)
        out_sample_dir_name = format_stage_template(
            SAMPLE_DIR_TEMPLATE,
            index=sample_idx,
            index1=sample_idx + 1,
            sample_name=safe_sample_name,
            fabric_stem=safe_sample_name,
        )
        out_sample_dir = os.path.join(OUT_DIR, out_sample_dir_name)
        manual_obj_sample_dir = os.path.join(MANUAL_OBJ_DIR, out_sample_dir_name)
        gs_sample_dir = os.path.join(GS_DIR, out_sample_dir_name)
        out_image_dir = os.path.join(out_sample_dir, "images")
        sample_summary_path = os.path.join(out_sample_dir, SAMPLE_SUMMARY_FILE_NAME)
        planned_draped_zprj_path = os.path.join(out_sample_dir, DRAPED_ZPRJ_FILE_NAME)
        os.makedirs(out_sample_dir, exist_ok=True)
        os.makedirs(manual_obj_sample_dir, exist_ok=True)
        os.makedirs(gs_sample_dir, exist_ok=True)

        print("=" * 80)
        print(f"[Sample {sample_idx:03d}/{len(sample_dirs)}]")
        print(f"  source sample : {sample_dir}")
        print(f"  zfab          : {zfab_path}")
        print(f"  output        : {out_sample_dir}")
        print(f"  manual obj    : {manual_obj_sample_dir}")
        print(f"  3dgs          : {gs_sample_dir}")

        sample_record = {
            "sample_index": sample_idx,
            "source_sample_dir": sample_dir,
            "zfab_path": zfab_path,
            "output_dir": out_sample_dir,
            "output_files": {
                "draped_zprj": planned_draped_zprj_path,
                "manual_obj_dir": manual_obj_sample_dir,
                "gs_dir": gs_sample_dir,
                "sample_summary_json": sample_summary_path,
                "material_json": None,
            },
            "status": "started"
        }

        try:
            # 1. base A-pose scene reload
            new_project_and_import_base()

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

            # 6. material.json 복사
            material_dst = None
            material_data = None
            material_json_error = None
            if material_src is not None:
                material_dst = os.path.join(out_sample_dir, "material.json")
                copy_file(material_src, material_dst)
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
                    "manual_obj_dir": manual_obj_sample_dir,
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
