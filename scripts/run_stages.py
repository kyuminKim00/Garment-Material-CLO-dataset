import argparse
import json
import runpy
import subprocess
import sys
from pathlib import Path


def current_script_path():
    script_file = globals().get("__file__", "")
    if not script_file or str(script_file).startswith("<"):
        return None
    try:
        return Path(script_file).expanduser().resolve()
    except Exception:
        return Path(script_file).expanduser()


SCRIPT_PATH = current_script_path()
CONFIG_JSON_PATH = r"/home/cgna/km/Garment-Material-CLO-dataset/dataset_config.json"


def script_argv():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]

    argv = sys.argv[1:]
    cleaned = []
    skip_next = False
    for item in argv:
        if skip_next:
            skip_next = False
            continue
        if item == "--python":
            skip_next = True
            continue
        if item in ("--background", "-b"):
            continue
        if SCRIPT_PATH and Path(item).name == SCRIPT_PATH.name:
            continue
        cleaned.append(item)
    return cleaned


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run the exact dataset stages listed in pipeline.run_stages from config. "
            "Paste/run this inside CLO Python for stage 01; "
            "stage 02 generates avatar body proxy GT inside CLO Python; "
            "stage 03 launches Blender in background mode; "
            "stage 04 launches the Gaussian Splatting trainer."
        )
    )
    parser.add_argument(
        "--config",
        default=CONFIG_JSON_PATH,
        help="Dataset config JSON path.",
    )
    parser.add_argument(
        "--blender",
        default="",
        help="Override pipeline.blender_executable for stage 03 rendering.",
    )
    parser.add_argument(
        "--python",
        default="",
        help="Override pipeline.python_executable for stage 04 training launcher.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without running them.",
    )
    return parser.parse_args(script_argv())


def load_config(path):
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def deep_get(obj, keys, default=None):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def parse_stage_value(value, source):
    try:
        stage = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source} must contain integers from 1 to 4") from exc
    if stage < 1 or stage > 4:
        raise ValueError(f"{source} must contain integers from 1 to 4")
    return stage


def get_run_stages(config):
    configured_stages = deep_get(config, ["pipeline", "run_stages"], None)
    if configured_stages is not None:
        if not isinstance(configured_stages, list):
            raise ValueError("pipeline.run_stages must be a list like [1, 2, 3, 4]")
        stages = [
            parse_stage_value(stage, "pipeline.run_stages")
            for stage in configured_stages
        ]
        seen = set()
        deduped = []
        for stage in stages:
            if stage in seen:
                continue
            seen.add(stage)
            deduped.append(stage)
        return deduped

    run_until_stage = deep_get(config, ["pipeline", "run_until_stage"], 4)
    try:
        run_until_stage = int(run_until_stage)
    except (TypeError, ValueError) as exc:
        raise ValueError("pipeline.run_until_stage must be an integer from 0 to 4") from exc
    if run_until_stage < 0 or run_until_stage > 4:
        raise ValueError("pipeline.run_until_stage must be an integer from 0 to 4")
    return list(range(1, run_until_stage + 1))


def choose_cli_or_config(cli_value, config, key_path, default):
    if cli_value:
        return cli_value
    return deep_get(config, key_path, default)


def resolve_config_path(value):
    return Path(value).expanduser().resolve()


def resolve_path(value, base_dir):
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def resolve_scripts_dir(config, config_dir):
    scripts_dir = (
        deep_get(config, ["paths", "scripts_dir"], "")
        or deep_get(config, ["pipeline", "scripts_dir"], "")
    )
    if scripts_dir:
        return resolve_path(scripts_dir, config_dir)
    if SCRIPT_PATH and SCRIPT_PATH.exists():
        return SCRIPT_PATH.parent
    return (config_dir / "scripts").resolve()


def require_script(scripts_dir, file_name):
    script_path = scripts_dir / file_name
    if not script_path.exists():
        raise FileNotFoundError(
            f"Stage script not found: {script_path}. "
            "Set paths.scripts_dir in dataset_config.json to the folder containing the stage scripts."
        )
    return script_path


def command_text(command):
    return " ".join(f'"{part}"' if " " in str(part) else str(part) for part in command)


def run_python_script_in_current_process(name, script_path, config_path, dry_run=False):
    print("=" * 80)
    print(f"[{name}]")
    print(f"{script_path} --config {config_path}")
    if dry_run:
        return

    old_argv = sys.argv[:]
    try:
        sys.argv = [str(script_path), "--config", str(config_path)]
        runpy.run_path(str(script_path), run_name="__main__")
    finally:
        sys.argv = old_argv


def run_subprocess_step(name, command, cwd, dry_run=False):
    print("=" * 80)
    print(f"[{name}]")
    print(command_text(command))
    if dry_run:
        return

    completed = subprocess.run(command, cwd=str(cwd))
    if completed.returncode != 0:
        raise SystemExit(f"{name} failed with exit code {completed.returncode}")


def main():
    args = parse_args()
    config_path_obj = resolve_config_path(args.config)
    config = load_config(config_path_obj)
    config_dir = config_path_obj.parent
    scripts_dir = resolve_scripts_dir(config, config_dir)
    repo_root = scripts_dir.parent
    config_path = str(config_path_obj)
    run_stages = get_run_stages(config)
    blender_executable = choose_cli_or_config(
        args.blender,
        config,
        ["pipeline", "blender_executable"],
        "blender",
    )
    python_executable = choose_cli_or_config(
        args.python,
        config,
        ["pipeline", "python_executable"],
        "python",
    )

    stage_03 = [
        blender_executable,
        "--background",
        "--python",
        str(require_script(scripts_dir, "03_blender_render.py")),
        "--",
        "--config",
        config_path,
    ]
    stage_04 = [
        python_executable,
        str(require_script(scripts_dir, "04_gs_train.py")),
        "--config",
        config_path,
    ]

    print("=" * 80)
    print(f"[Run stages] requested stages: {run_stages}")
    print(f"[Config] {config_path}")
    print(f"[Scripts] {scripts_dir}")

    stage_actions = {
        1: lambda: run_python_script_in_current_process(
            "01_draped_garments",
            require_script(scripts_dir, "01_clo_make_dataset.py"),
            config_path,
            args.dry_run,
        ),
        2: lambda: run_python_script_in_current_process(
            "02_body_proxy_gt",
            require_script(scripts_dir, "02_generate_proxy.py"),
            config_path,
            args.dry_run,
        ),
        3: lambda: run_subprocess_step("03_blender_multiview", stage_03, repo_root, args.dry_run),
        4: lambda: run_subprocess_step("04_3dgs", stage_04, repo_root, args.dry_run),
    }

    for stage in run_stages:
        stage_actions[stage]()

    print("=" * 80)
    if not run_stages:
        print("[Done] no dataset stages were run")
    else:
        print(f"[Done] completed requested stages: {run_stages}")


if __name__ == "__main__":
    main()
