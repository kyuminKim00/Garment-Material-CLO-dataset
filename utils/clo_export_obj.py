import argparse
import json
import os
from pathlib import Path


DEFAULT_FUNCTION_NAMES = ("ExportOBJW",)


def _load_export_api():
    import export_api  # type: ignore

    return export_api


def _set_if_present(obj, name, value, log):
    if hasattr(obj, name):
        try:
            setattr(obj, name, value)
            log["set"][name] = value
            return True
        except Exception as exc:
            log["failed"][name] = repr(exc)
    return False


def make_basic_option(
    export_garment=True,
    export_avatar=False,
    export_light=False,
    export_fabric=False,
    single_object=True,
    include_hidden=False,
    scale=0.01,
    save_in_zip=False,
    show_dialog=False,
    **unused_options,
):
    import ApiTypes  # type: ignore

    option = ApiTypes.ImportExportOption()
    log = {"set": {}, "failed": {}}

    for name in ("bExportGarment", "exportGarment", "ExportGarment"):
        if _set_if_present(option, name, export_garment, log):
            break
    for name in ("bExportAvatar", "exportAvatar", "ExportAvatar"):
        if _set_if_present(option, name, export_avatar, log):
            break
    for name in ("bExportLight", "exportLight", "ExportLight"):
        if _set_if_present(option, name, export_light, log):
            break
    for name in ("bExportFabric", "exportFabric", "ExportFabric"):
        if _set_if_present(option, name, export_fabric, log):
            break
    for name in ("bSingleObject", "singleObject", "SingleObject"):
        if _set_if_present(option, name, single_object, log):
            break
    for name in ("bIncludeHiddenObject", "includeHiddenObject", "IncludeHiddenObject"):
        if _set_if_present(option, name, include_hidden, log):
            break
    for name in ("scale", "Scale", "fScale"):
        if _set_if_present(option, name, scale, log):
            break
    for name in ("bSaveInZip", "saveInZip", "SaveInZip"):
        if _set_if_present(option, name, save_in_zip, log):
            break
    for name in ("bShowDialog", "showDialog", "bUseDialog", "useDialog", "bWithDialog", "withDialog", "dialog"):
        if _set_if_present(option, name, show_dialog, log):
            break

    return option, log


def _default_calls(func, out_obj_path, option):
    if option is None:
        return []
    return [("path_import_export_option", lambda: func(out_obj_path, option))]


def _default_bundle(out_obj_path):
    obj_path = os.path.abspath(out_obj_path)
    obj_dir = os.path.dirname(obj_path)
    files = []
    if os.path.isdir(obj_dir):
        files = [
            os.path.abspath(os.path.join(obj_dir, name))
            for name in sorted(os.listdir(obj_dir))
            if os.path.isfile(os.path.join(obj_dir, name))
        ]

    mtl_path = os.path.splitext(obj_path)[0] + ".mtl"
    return {
        "obj_path": obj_path if os.path.exists(obj_path) else None,
        "mtl_path": mtl_path if os.path.exists(mtl_path) else None,
        "files": files,
    }


def export_obj(
    out_obj_path,
    function_names=DEFAULT_FUNCTION_NAMES,
    option=None,
    export_api_module=None,
    collect_callback=None,
):
    out_obj_path = os.path.abspath(str(out_obj_path))
    os.makedirs(os.path.dirname(out_obj_path), exist_ok=True)

    api = export_api_module or _load_export_api()
    attempts = []

    for func_name in function_names:
        func = getattr(api, func_name, None)
        if not callable(func):
            attempts.append({"function": func_name, "status": "missing"})
            continue

        calls = _default_calls(func, out_obj_path, option)
        for signature_name, call in calls:
            try:
                result = call()
                bundle = collect_callback() if collect_callback else _default_bundle(out_obj_path)
                attempts.append(
                    {
                        "function": func_name,
                        "signature": signature_name,
                        "status": "called",
                        "result": str(result),
                        "obj_exists": bool(bundle.get("obj_path")),
                    }
                )
                if bundle.get("obj_path"):
                    return {
                        "ok": True,
                        "bundle": bundle,
                        "function": func_name,
                        "signature": signature_name,
                        "result": str(result),
                        "attempts": attempts,
                    }
            except Exception as exc:
                attempts.append(
                    {
                        "function": func_name,
                        "signature": signature_name,
                        "status": "failed",
                        "error": repr(exc),
                    }
                )

    return {
        "ok": False,
        "bundle": None,
        "function": None,
        "signature": None,
        "result": None,
        "attempts": attempts,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Export the current CLO project garment as an OBJ bundle.")
    parser.add_argument("--out_dir", required=True, help="Directory for OBJ/MTL/textures.")
    parser.add_argument("--obj_file", default="obj.obj", help="OBJ file name inside out_dir.")
    parser.add_argument("--export_avatar", action="store_true", help="Include avatar mesh.")
    parser.add_argument("--scale", type=float, default=0.01, help="OBJ export scale.")
    return parser.parse_args()


def main():
    args = parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_obj_path = out_dir / args.obj_file
    option, option_log = make_basic_option(export_avatar=args.export_avatar, scale=args.scale)
    result = export_obj(str(out_obj_path), option=option)

    log_path = out_dir / "export_log.json"
    with log_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "obj_path": str(out_obj_path),
                "option": option_log,
                "result": result,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    if not result["ok"]:
        raise RuntimeError(f"OBJ export failed. See {log_path}")

    print("Export result:", result)


if __name__ == "__main__":
    main()
