import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import import_api
    import utility_api
    CLO_API_IMPORT_ERROR = None
except Exception as e:
    import_api = None
    utility_api = None
    CLO_API_IMPORT_ERROR = e


CONFIG_JSON_PATH = Path(r"C:\Users\CGnA\Desktop\CLO\dataset_config.json")


def resolve_script_path():
    script_file = globals().get("__file__", "")
    if script_file and not str(script_file).startswith("<"):
        candidate = Path(script_file).expanduser()
        try:
            candidate = candidate.resolve()
        except Exception:
            pass
        if candidate.exists():
            return candidate
    return (CONFIG_JSON_PATH.parent / "scripts" / "02_generate_proxy.py").resolve()


def find_repo_root(script_path):
    candidates = [
        script_path.parent.parent,
        CONFIG_JSON_PATH.parent,
        Path.cwd(),
        Path.cwd() / "CLO",
        Path.cwd().parent,
        Path.cwd().parent / "CLO",
    ]
    seen = set()
    for candidate in candidates:
        try:
            candidate = candidate.expanduser().resolve()
        except Exception:
            continue
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        if (candidate / "utils" / "clo_export_avatar_obj.py").exists():
            return candidate
    return script_path.parent.parent.resolve()


SCRIPT_PATH = resolve_script_path()
SCRIPT_DIR = SCRIPT_PATH.parent
REPO_ROOT = find_repo_root(SCRIPT_PATH)
AVATAR_EXPORT_OBJ_FILE = REPO_ROOT / "utils" / "clo_export_avatar_obj.py"
AVATAR_PROXY_GT_FILE = REPO_ROOT / "utils" / "generate_avatar_proxy_gt.py"


def load_module(name, path):
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Module file does not exist: {path}")
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    spec.loader.exec_module(module)
    return module


try:
    avatar_export_module = load_module("clo_export_avatar_obj_stage_02", AVATAR_EXPORT_OBJ_FILE)
    AVATAR_EXPORT_IMPORT_ERROR = None
except Exception as e:
    avatar_export_module = None
    AVATAR_EXPORT_IMPORT_ERROR = e

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Generate avatar body proxy GT from CLO garment projects.")
    parser.add_argument("--config", default=str(CONFIG_JSON_PATH), help="Dataset config JSON path.")
    return parser.parse_args(sys.argv[1:] if argv is None else argv)


def load_config(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, indent=2, ensure_ascii=False)


def read_json(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


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


def safe_name(value):
    text = str(value)
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip() or "unnamed"


def format_template(template, **values):
    try:
        return str(template).format(**values)
    except Exception:
        return str(template)


def resolve_path(value, base_dir):
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = Path(base_dir) / path
    return path.resolve()


def require_keys(config, keys, section_name):
    missing = [key for key in keys if key not in config]
    if missing:
        raise RuntimeError(f"{section_name} is missing required config keys: {', '.join(missing)}")


def ensure_clo_api():
    if CLO_API_IMPORT_ERROR is None:
        return
    raise RuntimeError(
        "CLO Python API modules are not available. "
        "Run stage 02 inside CLO Python. "
        f"Import error: {CLO_API_IMPORT_ERROR}"
    )


def load_body_proxy_config(config, config_dir):
    output_root_value = (
        deep_get(config, ["project", "output_dir"])
        or deep_get(config, ["project", "dataset_root"])
        or ""
    )
    if not output_root_value:
        raise RuntimeError("project.output_dir is required")
    output_root = resolve_path(output_root_value, config_dir)

    body_proxy_config = deep_get(config, ["body_proxy_gt"], {})
    if not isinstance(body_proxy_config, dict):
        raise RuntimeError("body_proxy_gt must be an object")

    required = [
        "enabled",
        "output_dir",
        "body_dir_template",
        "avatar_obj_file",
        "avatar_meta_file",
        "proxy_dir",
        "proxy_json_file",
        "proxy_tensor_file",
        "proxy_png_dir",
        "export_scale",
        "num_slices",
        "top_k",
        "slice_min",
        "slice_max",
        "png_size",
        "reuse_existing",
        "stop_on_first_failure",
        "python_executable",
    ]
    require_keys(body_proxy_config, required, "body_proxy_gt")

    draped_dir = deep_get(config, ["naming", "draped_dir"], "")
    if not draped_dir:
        raise RuntimeError("naming.draped_dir is required")

    dataset_summary_json = (
        deep_get(config, ["stage_2_body_proxy_gt", "inputs", "dataset_summary_json"])
        or deep_get(config, ["body_proxy_gt", "dataset_summary_json"])
        or os.path.join(str(output_root), str(draped_dir), "dataset_summary.json")
    )

    return {
        "enabled": parse_bool(body_proxy_config["enabled"], False),
        "output_root": output_root,
        "dataset_summary_json": resolve_path(dataset_summary_json, output_root),
        "output_dir": resolve_path(body_proxy_config["output_dir"], output_root),
        "body_dir_template": str(body_proxy_config["body_dir_template"]),
        "avatar_obj_file": str(body_proxy_config["avatar_obj_file"]),
        "avatar_meta_file": str(body_proxy_config["avatar_meta_file"]),
        "proxy_dir": str(body_proxy_config["proxy_dir"]),
        "proxy_json_file": str(body_proxy_config["proxy_json_file"]),
        "proxy_tensor_file": str(body_proxy_config["proxy_tensor_file"]),
        "proxy_png_dir": str(body_proxy_config["proxy_png_dir"]),
        "export_scale": float(body_proxy_config["export_scale"]),
        "num_slices": int(body_proxy_config["num_slices"]),
        "top_k": int(body_proxy_config["top_k"]),
        "slice_min": float(body_proxy_config["slice_min"]),
        "slice_max": float(body_proxy_config["slice_max"]),
        "png_size": int(body_proxy_config["png_size"]),
        "reuse_existing": parse_bool(body_proxy_config["reuse_existing"], True),
        "stop_on_first_failure": parse_bool(body_proxy_config["stop_on_first_failure"], True),
        "python_executable": str(
            body_proxy_config["python_executable"]
            or deep_get(config, ["pipeline", "python_executable"], "python")
        ),
    }


def discover_bodies(dataset_summary):
    bodies = []
    seen = set()
    for sample in dataset_summary.get("samples", []):
        if sample.get("status") != "success":
            continue
        body_id = safe_name(sample.get("body_id") or sample.get("garment_id") or "body")
        garment_zprj = sample.get("garment_zprj", "")
        key = (body_id.lower(), os.path.normcase(os.path.abspath(garment_zprj)) if garment_zprj else "")
        if key in seen:
            continue
        seen.add(key)
        bodies.append(
            {
                "body_id": body_id,
                "garment_id": safe_name(sample.get("garment_id") or body_id),
                "garment_index": len(bodies),
                "garment_zprj": garment_zprj,
            }
        )
    return bodies


def get_body_proxy_paths(settings, body):
    body_dir_name = format_template(
        settings["body_dir_template"],
        body_id=body["body_id"],
        garment_id=body["garment_id"],
        garment_index=body["garment_index"],
    )
    body_dir = settings["output_dir"] / body_dir_name
    proxy_dir = body_dir / settings["proxy_dir"]
    return {
        "body_id": body["body_id"],
        "body_dir": body_dir,
        "avatar_obj": body_dir / settings["avatar_obj_file"],
        "avatar_meta": body_dir / settings["avatar_meta_file"],
        "proxy_dir": proxy_dir,
        "proxy_json": proxy_dir / settings["proxy_json_file"],
        "proxy_tensor": proxy_dir / settings["proxy_tensor_file"],
        "proxy_png_dir": proxy_dir / settings["proxy_png_dir"],
    }


def import_project_for_body(zprj_path):
    try:
        utility_api.NewProject()
    except Exception as e:
        print(f"[Warning] NewProject failed or unavailable: {e}")

    result = import_api.ImportFile(zprj_path)
    if result == "" or result is False:
        raise RuntimeError(f"Import garment ZPRJ failed: {zprj_path}")

    try:
        utility_api.Refresh3DWindow()
    except Exception:
        pass
    return result


def generate_body_proxy(settings, body):
    if avatar_export_module is None:
        raise RuntimeError(f"Failed to import utils.clo_export_avatar_obj: {repr(AVATAR_EXPORT_IMPORT_ERROR)}")
    if not AVATAR_PROXY_GT_FILE.exists():
        raise RuntimeError(f"Proxy generator script does not exist: {AVATAR_PROXY_GT_FILE}")

    paths = get_body_proxy_paths(settings, body)
    paths["body_dir"].mkdir(parents=True, exist_ok=True)
    paths["proxy_dir"].mkdir(parents=True, exist_ok=True)

    avatar_reused = (
        settings["reuse_existing"]
        and paths["avatar_obj"].exists()
        and paths["avatar_meta"].exists()
    )
    export_info = None
    post_info = None
    bbox_info = None
    import_result = None
    if avatar_reused:
        try:
            bbox_info = read_json(str(paths["avatar_meta"])).get("avatar_geometry")
        except Exception:
            bbox_info = None
    else:
        if not body.get("garment_zprj"):
            raise RuntimeError(f"No garment_zprj recorded for body_id={body['body_id']}")
        if not os.path.exists(body["garment_zprj"]):
            raise RuntimeError(f"Garment ZPRJ does not exist: {body['garment_zprj']}")
        import_result = import_project_for_body(body["garment_zprj"])
        clo_option_scale = float(getattr(avatar_export_module, "CLO_OPTION_SCALE", 1.0))
        export_info = avatar_export_module.export_avatar_obj(str(paths["avatar_obj"]), clo_option_scale)
        post_info = avatar_export_module.rewrite_geometry_only_obj(
            str(paths["avatar_obj"]),
            manual_scale=settings["export_scale"],
            geometry_only=True,
        )
        bbox_info = avatar_export_module.parse_obj_bbox(str(paths["avatar_obj"]))
        write_json(
            str(paths["avatar_meta"]),
            {
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "base_zprj": os.path.abspath(body["garment_zprj"]),
                "import_result": repr(import_result),
                "obj_path": str(paths["avatar_obj"]),
                "export_scale_requested": settings["export_scale"],
                "clo_option_scale": clo_option_scale,
                "manual_vertex_scale_applied": settings["export_scale"],
                "coordinate_convention": {
                    "height_axis": "y",
                    "scale_note": "Values are measured from the final OBJ after manually scaling vertex coordinates.",
                },
                "avatar_geometry": bbox_info,
                "export_info": export_info,
                "post_process": post_info,
            },
        )

    proxy_reused = (
        settings["reuse_existing"]
        and paths["proxy_json"].exists()
        and paths["proxy_tensor"].exists()
    )
    proxy_result = None
    if not proxy_reused:
        command = [
            settings["python_executable"],
            str(AVATAR_PROXY_GT_FILE),
            "--obj",
            str(paths["avatar_obj"]),
            "--out_dir",
            str(paths["proxy_dir"]),
            "--num_slices",
            str(settings["num_slices"]),
            "--top_k",
            str(settings["top_k"]),
            "--slice_min",
            str(settings["slice_min"]),
            "--slice_max",
            str(settings["slice_max"]),
            "--png_size",
            str(settings["png_size"]),
            "--json_name",
            settings["proxy_json_file"],
            "--tensor_name",
            settings["proxy_tensor_file"],
            "--png_dir_name",
            settings["proxy_png_dir"],
        ]
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        proxy_result = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode != 0:
            raise RuntimeError(
                "External proxy generation failed with exit code "
                f"{completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
            )

    return {
        "enabled": True,
        "status": "success",
        "body_id": body["body_id"],
        "garment_id": body["garment_id"],
        "garment_zprj": body.get("garment_zprj", ""),
        "body_dir": str(paths["body_dir"]),
        "avatar_obj": str(paths["avatar_obj"]),
        "avatar_meta": str(paths["avatar_meta"]),
        "proxy_dir": str(paths["proxy_dir"]),
        "proxy_json": str(paths["proxy_json"]),
        "proxy_tensor": str(paths["proxy_tensor"]),
        "proxy_png_dir": str(paths["proxy_png_dir"]),
        "avatar_reused": avatar_reused,
        "proxy_reused": proxy_reused,
        "export_info": export_info,
        "post_process": post_info,
        "avatar_geometry": bbox_info,
        "proxy_result": proxy_result,
    }


def attach_proxy_to_sample_summary(sample, body_record):
    sample["body_proxy_gt"] = body_record
    output_files = sample.setdefault("output_files", {})
    output_files["body_proxy_json"] = body_record.get("proxy_json")
    output_files["body_proxy_tensor"] = body_record.get("proxy_tensor")
    output_files["body_proxy_dir"] = body_record.get("proxy_dir")
    output_files["avatar_obj"] = body_record.get("avatar_obj")
    output_files["avatar_meta"] = body_record.get("avatar_meta")

    summary_path = output_files.get("sample_summary_json")
    if not summary_path:
        return
    if not os.path.exists(summary_path):
        return
    sample_summary = read_json(summary_path)
    sample_summary["body_proxy_gt"] = body_record
    sample_output_files = sample_summary.setdefault("output_files", {})
    sample_output_files.update(
        {
            "body_proxy_json": body_record.get("proxy_json"),
            "body_proxy_tensor": body_record.get("proxy_tensor"),
            "body_proxy_dir": body_record.get("proxy_dir"),
            "avatar_obj": body_record.get("avatar_obj"),
            "avatar_meta": body_record.get("avatar_meta"),
        }
    )
    write_json(summary_path, sample_summary)


def main(argv=None):
    args = parse_args(argv)
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(str(config_path))
    settings = load_body_proxy_config(config, config_path.parent)

    if not settings["enabled"]:
        print("[BodyProxy] disabled by config")
        return

    ensure_clo_api()
    if not settings["dataset_summary_json"].exists():
        raise RuntimeError(f"Dataset summary does not exist: {settings['dataset_summary_json']}")

    dataset_summary = read_json(str(settings["dataset_summary_json"]))
    bodies = discover_bodies(dataset_summary)
    if not bodies:
        raise RuntimeError("No successful bodies found in dataset summary")

    stage_summary = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dataset_summary_json": str(settings["dataset_summary_json"]),
        "output_dir": str(settings["output_dir"]),
        "settings": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in settings.items()
            if key not in ("output_root",)
        },
        "num_bodies": len(bodies),
        "bodies": [],
    }

    body_records = {}
    for body in bodies:
        print("=" * 80)
        print(f"[BodyProxy] body_id={body['body_id']}")
        try:
            record = generate_body_proxy(settings, body)
            body_records[body["body_id"]] = record
            stage_summary["bodies"].append(record)
            print(f"  proxy: {record['proxy_json']}")
        except Exception as e:
            record = {
                "enabled": True,
                "status": "failed",
                "body_id": body["body_id"],
                "garment_id": body["garment_id"],
                "garment_zprj": body.get("garment_zprj", ""),
                "error": str(e),
            }
            stage_summary["bodies"].append(record)
            print(f"  [Failed] {e}")
            if settings["stop_on_first_failure"]:
                stage_summary["aborted"] = True
                stage_summary["abort_reason"] = str(e)
                break

    for sample in dataset_summary.get("samples", []):
        record = body_records.get(safe_name(sample.get("body_id") or sample.get("garment_id") or "body"))
        if record:
            attach_proxy_to_sample_summary(sample, record)

    stage_summary["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    stage_summary["num_success"] = len([item for item in stage_summary["bodies"] if item.get("status") == "success"])
    stage_summary["num_failed"] = len([item for item in stage_summary["bodies"] if item.get("status") == "failed"])
    dataset_summary["body_proxy_gt"] = stage_summary
    dataset_summary["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    settings["output_dir"].mkdir(parents=True, exist_ok=True)
    write_json(str(settings["output_dir"] / "proxy_summary.json"), stage_summary)
    write_json(str(settings["dataset_summary_json"]), dataset_summary)
    print("=" * 80)
    print(f"[Finished] proxy summary: {settings['output_dir'] / 'proxy_summary.json'}")


if __name__ == "__main__":
    main()
