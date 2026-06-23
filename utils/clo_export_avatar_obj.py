# Run inside CLO Python Script Editor.
#
# Export only the current avatar as OBJ and write simple scale/height metadata.
# The current CLO project must already contain the avatar you want to export.

import argparse
import importlib.util
import inspect
import json
import os
import sys
import time

try:
    import import_api
    import export_api
    CLO_API_IMPORT_ERROR = None
except Exception as e:
    import_api = None
    export_api = None
    CLO_API_IMPORT_ERROR = e


# =============================================================================
# Defaults
# =============================================================================

BASE_ZPRJ_PATH = ""  # Optional. Leave empty to export from the currently opened project.
OUT_DIR = ""
OBJ_FILE_NAME = "avatar.obj"
META_FILE_NAME = "avatar_meta.json"

# Manual post-export geometry scale. CLO's OBJ scale option is unreliable in some
# versions, so the script rewrites vertex coordinates after export.
EXPORT_SCALE = 0.01

# Keep CLO export itself at 1.0, then apply EXPORT_SCALE manually to vertices.
CLO_OPTION_SCALE = 1.0

# Keep only geometry lines in the final OBJ: v and f.
WRITE_GEOMETRY_ONLY_OBJ = True

EXPORT_FUNCTION_CANDIDATES = [
    "ExportOBJW",
]

SCRIPT_FILE = globals().get("__file__", "")
if SCRIPT_FILE and not str(SCRIPT_FILE).startswith("<"):
    SCRIPT_FILE = os.path.abspath(SCRIPT_FILE)
else:
    SCRIPT_FILE = ""
SCRIPT_DIR = os.path.abspath(os.path.dirname(SCRIPT_FILE)) if SCRIPT_FILE else os.getcwd()


def find_util_export_obj_file():
    candidates = [
        os.path.join(SCRIPT_DIR, "clo_export_obj.py"),
        os.path.join(os.path.dirname(SCRIPT_DIR), "utils", "clo_export_obj.py"),
        os.path.join(os.getcwd(), "utils", "clo_export_obj.py"),
        os.path.join(os.getcwd(), "clo_export_obj.py"),
    ]
    seen = set()
    for candidate in candidates:
        candidate = os.path.abspath(candidate)
        key = os.path.normcase(candidate)
        if key in seen:
            continue
        seen.add(key)
        if os.path.exists(candidate):
            return candidate, candidates
    return os.path.abspath(candidates[0]), candidates


UTIL_EXPORT_OBJ_FILE, UTIL_EXPORT_OBJ_CANDIDATES = find_util_export_obj_file()

try:
    spec = importlib.util.spec_from_file_location("clo_export_obj_util", UTIL_EXPORT_OBJ_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec: {UTIL_EXPORT_OBJ_FILE}")
    clo_export_obj_util = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clo_export_obj_util)
    export_clo_obj_util = clo_export_obj_util.export_obj
    make_basic_option_util = clo_export_obj_util.make_basic_option
    UTIL_IMPORT_ERROR = None
except Exception as e:
    clo_export_obj_util = None
    export_clo_obj_util = None
    make_basic_option_util = None
    UTIL_IMPORT_ERROR = e


# =============================================================================
# Utilities
# =============================================================================

def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Export current CLO avatar as OBJ.")
    parser.add_argument("--base_zprj", default=BASE_ZPRJ_PATH, help="Optional ZPRJ to open before export.")
    parser.add_argument("--out_dir", default=OUT_DIR, help="Output directory.")
    parser.add_argument("--obj_name", default=OBJ_FILE_NAME, help="Output OBJ file name.")
    parser.add_argument("--meta_name", default=META_FILE_NAME, help="Output metadata JSON file name.")
    parser.add_argument("--scale", type=float, default=EXPORT_SCALE, help="CLO OBJ export scale.")
    args, _ = parser.parse_known_args(argv)
    return args


def import_project_if_needed(base_zprj):
    if not base_zprj:
        return None
    if import_api is None:
        raise RuntimeError(f"CLO API import failed: {repr(CLO_API_IMPORT_ERROR)}")
    if not os.path.exists(base_zprj):
        raise RuntimeError(f"Base ZPRJ does not exist: {base_zprj}")

    result = import_api.ImportFile(base_zprj)
    if result == "" or result is False:
        raise RuntimeError(f"Import base ZPRJ failed: {base_zprj}")
    return result


def available_export_symbols():
    if export_api is None:
        return []
    return sorted(
        name for name in dir(export_api)
        if "export" in name.lower() or "obj" in name.lower() or "option" in name.lower()
    )


def make_export_option(scale):
    """
    Build CLO OBJ export option if the current CLO Python API exposes an option class.
    Different CLO versions expose slightly different symbols, so this function tries
    the common option constructors and falls back to None.
    """
    if export_api is None:
        return None, {"error": "export_api is None"}

    option_class_names = [
        "ExportOBJOption",
        "ExportObjOption",
        "ExportOption",
        "OBJExportOption",
        "ObjExportOption",
    ]

    log = {"attempts": []}
    for name in option_class_names:
        cls = getattr(export_api, name, None)
        if cls is None:
            continue
        try:
            option = cls()
            set_option_fields(option, scale)
            log["attempts"].append({"name": name, "ok": True, "repr": repr(option)})
            return option, log
        except Exception as e:
            log["attempts"].append({"name": name, "ok": False, "error": repr(e)})

    # Some CLO builds define option types in CLOAPIInterface.
    try:
        import CLOAPIInterface
        for name in option_class_names:
            cls = getattr(CLOAPIInterface, name, None)
            if cls is None:
                continue
            try:
                option = cls()
                set_option_fields(option, scale)
                log["attempts"].append({"name": "CLOAPIInterface." + name, "ok": True, "repr": repr(option)})
                return option, log
            except Exception as e:
                log["attempts"].append({"name": "CLOAPIInterface." + name, "ok": False, "error": repr(e)})
    except Exception as e:
        log["clo_api_interface_error"] = repr(e)

    log["fallback"] = "None option"
    return None, log


def try_set(obj, names, value):
    results = []
    for name in names:
        try:
            if hasattr(obj, name):
                attr = getattr(obj, name)
                if callable(attr):
                    attr(value)
                else:
                    setattr(obj, name, value)
                results.append({"field": name, "ok": True})
        except Exception as e:
            results.append({"field": name, "ok": False, "error": repr(e)})
    return results


def set_option_fields(option, scale):
    # Field names are intentionally broad because CLO API names vary by version.
    try_set(option, ["bExportGarment", "exportGarment", "ExportGarment", "garment", "export_garment"], False)
    try_set(option, ["bExportAvatar", "exportAvatar", "ExportAvatar", "avatar", "export_avatar"], True)
    try_set(option, ["bExportLight", "exportLight", "ExportLight", "export_light"], False)
    try_set(option, ["bExportFabric", "exportFabric", "ExportFabric", "export_fabric"], False)
    try_set(option, ["bSingleObject", "singleObject", "SingleObject", "single_object"], True)
    try_set(option, ["bIncludeHidden", "includeHidden", "IncludeHidden", "include_hidden"], False)
    try_set(option, ["bSaveInZip", "saveInZip", "SaveInZip", "save_in_zip"], False)
    try_set(option, ["bShowDialog", "showDialog", "ShowDialog", "show_dialog"], False)
    try_set(option, ["scale", "Scale", "fScale", "m_fScale"], float(scale))


def call_export_function(fn, obj_path, option, scale):
    """
    Try common signatures:
      ExportOBJW(path, option)
      ExportOBJW(path)
      ExportOBJW(path, exportGarment, exportAvatar, ...)
    """
    attempts = []
    candidates = []
    if option is not None:
        candidates.append((obj_path, option))
    candidates.extend([
        (obj_path,),
        (obj_path, False, True),
        (obj_path, False, True, False),
        (obj_path, False, True, False, True),
        (obj_path, False, True, False, True, False, float(scale)),
    ])

    for args in candidates:
        try:
            result = fn(*args)
            attempts.append({"args": repr(args), "ok": bool(result), "result": repr(result)})
            if result is not False and result != "":
                return True, result, attempts
        except Exception as e:
            attempts.append({"args": repr(args), "ok": False, "error": repr(e)})

    return False, None, attempts


def export_avatar_obj(obj_path, scale):
    if export_api is None:
        raise RuntimeError(f"CLO API import failed: {repr(CLO_API_IMPORT_ERROR)}")

    os.makedirs(os.path.dirname(obj_path), exist_ok=True)

    util_result = try_export_with_existing_util(obj_path, scale)
    if util_result is not None:
        return util_result

    error = {
        "ok": False,
        "requested_obj_path": obj_path,
        "message": "API-only export failed because utils/clo_export_obj.py could not be used.",
        "expected_api_path": "utils.clo_export_obj.export_obj(... ExportOBJW ...)",
        "export_attempts": [],
        "available_export_symbols": available_export_symbols(),
        "util_export_obj_path": UTIL_EXPORT_OBJ_FILE,
        "util_export_obj_candidates": UTIL_EXPORT_OBJ_CANDIDATES,
        "util_import_error": repr(UTIL_IMPORT_ERROR),
    }
    write_json(os.path.join(os.path.dirname(obj_path), "avatar_export_error.json"), error)
    raise RuntimeError("Avatar OBJ export failed. See avatar_export_error.json.")


def collect_obj_bundle(out_dir, preferred_obj_path):
    obj_path = preferred_obj_path if os.path.exists(preferred_obj_path) else None
    if obj_path is None:
        candidates = [
            os.path.join(out_dir, name)
            for name in os.listdir(out_dir)
            if name.lower().endswith(".obj")
        ]
        candidates.sort(key=lambda p: (os.path.getmtime(p), p), reverse=True)
        obj_path = candidates[0] if candidates else None

    mtl_path = None
    if obj_path and os.path.exists(obj_path):
        with open(obj_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if line.lower().startswith("mtllib "):
                    ref = line.split(None, 1)[1].strip().strip('"').strip("'")
                    candidate = os.path.join(os.path.dirname(obj_path), ref)
                    if os.path.exists(candidate):
                        mtl_path = candidate
                    break

    files = [p for p in [obj_path, mtl_path] if p]
    return {
        "obj_path": obj_path,
        "mtl_path": mtl_path,
        "files": files,
    }


def try_export_with_existing_util(obj_path, scale):
    if export_clo_obj_util is None or make_basic_option_util is None:
        return None

    option_kwargs = {
        "export_garment": False,
        "export_avatar": True,
        "export_light": False,
        "export_fabric": False,
        "single_object": True,
        "include_hidden": False,
        "scale": float(scale),
        "save_in_zip": False,
        "show_dialog": False,
    }

    try:
        option, option_log = make_basic_option_util(**option_kwargs)
    except Exception as e:
        error = {
            "ok": False,
            "stage": "make_basic_option",
            "option_kwargs": option_kwargs,
            "error": repr(e),
            "util_export_obj_path": UTIL_EXPORT_OBJ_FILE,
            "util_export_obj_candidates": UTIL_EXPORT_OBJ_CANDIDATES,
        }
        write_json(os.path.join(os.path.dirname(obj_path), "avatar_export_error.json"), error)
        raise RuntimeError("make_basic_option failed. See avatar_export_error.json.")

    result = export_clo_obj_util(
        obj_path,
        function_names=EXPORT_FUNCTION_CANDIDATES,
        option=option,
        export_api_module=export_api,
        collect_callback=lambda: collect_obj_bundle(os.path.dirname(obj_path), obj_path),
    )

    if result.get("ok") and os.path.exists(obj_path):
        return {
            "ok": True,
            "obj_path": obj_path,
            "function": "utils.clo_export_obj." + str(result.get("function")),
            "result": repr(result.get("result")),
            "option_log": option_log,
            "export_attempts": result.get("attempts", []),
            "bundle": result.get("bundle", {}),
        }

    error = {
        "ok": False,
        "stage": "export_obj",
        "requested_obj_path": obj_path,
        "option_log": option_log,
        "result": result,
        "util_export_obj_path": UTIL_EXPORT_OBJ_FILE,
        "util_export_obj_candidates": UTIL_EXPORT_OBJ_CANDIDATES,
    }
    write_json(os.path.join(os.path.dirname(obj_path), "avatar_export_error.json"), error)
    raise RuntimeError("API ExportOBJW failed. See avatar_export_error.json.")


def safe_signature(fn):
    try:
        return str(inspect.signature(fn))
    except Exception:
        return None


def parse_obj_bbox(obj_path):
    vertices = []
    faces = 0
    if not os.path.exists(obj_path):
        raise RuntimeError(f"OBJ does not exist: {obj_path}")

    with open(obj_path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                parts = line.strip().split()
                if len(parts) >= 4:
                    vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif line.startswith("f "):
                faces += 1

    if not vertices:
        raise RuntimeError(f"No vertices found in exported OBJ: {obj_path}")

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    bbox_min = [min(xs), min(ys), min(zs)]
    bbox_max = [max(xs), max(ys), max(zs)]
    bbox_size = [bbox_max[i] - bbox_min[i] for i in range(3)]

    return {
        "num_vertices": len(vertices),
        "num_faces": faces,
        "bbox_min": bbox_min,
        "bbox_max": bbox_max,
        "bbox_size": bbox_size,
        "height_y": bbox_size[1],
        "center": [
            0.5 * (bbox_min[0] + bbox_max[0]),
            0.5 * (bbox_min[1] + bbox_max[1]),
            0.5 * (bbox_min[2] + bbox_max[2]),
        ],
    }


def rewrite_geometry_only_obj(obj_path, manual_scale=1.0, geometry_only=True):
    """
    Rewrite OBJ after CLO export.

    Why:
      1. CLO's OBJ export scale option can be ignored depending on version/API path.
      2. For body proxy GT, texture/MTL/UV/material data are unnecessary.

    Output:
      - scaled v lines
      - vertex-only f lines
      - no mtllib/usemtl/vt/vn/texture references when geometry_only=True
    """
    if not os.path.exists(obj_path):
        raise RuntimeError(f"OBJ does not exist before post-process: {obj_path}")

    tmp_path = obj_path + ".tmp"
    num_v = 0
    num_f = 0
    num_skipped = 0

    with open(obj_path, "r", encoding="utf-8-sig", errors="ignore") as fin, \
            open(tmp_path, "w", encoding="utf-8") as fout:
        fout.write("# geometry-only avatar OBJ generated from CLO export\n")
        fout.write("# vertex coordinates manually scaled by {}\n".format(float(manual_scale)))

        for raw in fin:
            line = raw.strip()
            if not line:
                continue

            if line.startswith("v "):
                parts = line.split()
                if len(parts) < 4:
                    num_skipped += 1
                    continue
                x = float(parts[1]) * manual_scale
                y = float(parts[2]) * manual_scale
                z = float(parts[3]) * manual_scale
                fout.write("v {:.9f} {:.9f} {:.9f}\n".format(x, y, z))
                num_v += 1
                continue

            if line.startswith("f "):
                face_tokens = []
                for tok in line.split()[1:]:
                    vi = tok.split("/")[0]
                    if vi:
                        face_tokens.append(vi)
                if len(face_tokens) >= 3:
                    fout.write("f {}\n".format(" ".join(face_tokens)))
                    num_f += 1
                else:
                    num_skipped += 1
                continue

            if not geometry_only:
                # Keep non-texture geometry metadata only.
                if line.startswith(("o ", "g ", "s ")):
                    fout.write(line + "\n")
                else:
                    num_skipped += 1
            else:
                num_skipped += 1

    os.replace(tmp_path, obj_path)

    removed_files = remove_texture_sidecars(obj_path)
    return {
        "geometry_only": bool(geometry_only),
        "manual_scale": float(manual_scale),
        "num_vertices_written": int(num_v),
        "num_faces_written": int(num_f),
        "num_lines_skipped": int(num_skipped),
        "removed_sidecar_files": removed_files,
    }


def remove_texture_sidecars(obj_path):
    """
    Remove generated MTL/texture sidecars next to the OBJ.
    These files are generated by this export script and are not needed for proxy GT.
    """
    out_dir = os.path.dirname(obj_path)
    obj_stem = os.path.splitext(os.path.basename(obj_path))[0].lower()
    removed = []
    texture_exts = {".mtl", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".exr", ".tif", ".tiff"}

    try:
        names = os.listdir(out_dir)
    except Exception:
        return removed

    for name in names:
        path = os.path.join(out_dir, name)
        if os.path.abspath(path) == os.path.abspath(obj_path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in texture_exts:
            continue
        # Be conservative: remove common CLO sidecars in this output folder.
        lower = name.lower()
        if lower.startswith(obj_stem) or ext == ".mtl" or "texture" in lower or "diffuse" in lower or "normal" in lower:
            try:
                os.remove(path)
                removed.append(path)
            except Exception:
                pass

    return removed


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out_dir = os.path.abspath(args.out_dir)
    obj_path = os.path.abspath(os.path.join(out_dir, args.obj_name))
    meta_path = os.path.abspath(os.path.join(out_dir, args.meta_name))

    print("=" * 80)
    print("[CLO Avatar Export]")
    print(f"out_dir   : {out_dir}")
    print(f"obj_path  : {obj_path}")
    print(f"meta_path : {meta_path}")
    print(f"scale     : {args.scale}")
    print("=" * 80)

    imported = import_project_if_needed(args.base_zprj)
    export_info = export_avatar_obj(obj_path, CLO_OPTION_SCALE)
    post_info = rewrite_geometry_only_obj(
        obj_path,
        manual_scale=float(args.scale),
        geometry_only=WRITE_GEOMETRY_ONLY_OBJ,
    )
    bbox_info = parse_obj_bbox(obj_path)

    meta = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_zprj": os.path.abspath(args.base_zprj) if args.base_zprj else "",
        "import_result": repr(imported),
        "obj_path": obj_path,
        "export_scale_requested": float(args.scale),
        "clo_option_scale": float(CLO_OPTION_SCALE),
        "manual_vertex_scale_applied": float(args.scale),
        "coordinate_convention": {
            "height_axis": "y",
            "scale_note": "Values are measured from the final OBJ after manually scaling vertex coordinates.",
        },
        "avatar_geometry": bbox_info,
        "export_info": export_info,
        "post_process": post_info,
    }
    write_json(meta_path, meta)

    print("[Finished]")
    print(f"OBJ  : {obj_path}")
    print(f"META : {meta_path}")
    print(f"height_y: {bbox_info['height_y']}")


if __name__ == "__main__":
    main()
