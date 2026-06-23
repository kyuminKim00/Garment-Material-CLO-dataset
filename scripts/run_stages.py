import argparse
import json
import runpy
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
REPO_ROOT = SCRIPT_DIR.parent
CONFIG_JSON_PATH = r"C:\Users\CGnA\Desktop\CLO\dataset_config.json"


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
        if Path(item).name == SCRIPT_PATH.name:
            continue
        cleaned.append(item)
    return cleaned


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run the exact dataset stages listed in pipeline.run_stages from config. "
            "Paste/run this inside CLO Python for stage 01; "
            "stage 02 launches Blender in background mode; "
            "stage 03 launches the Gaussian Splatting trainer."
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
        help="Override pipeline.blender_executable for stage 02 rendering.",
    )
    parser.add_argument(
        "--python",
        default="",
        help="Override pipeline.python_executable for stage 03 training launcher.",
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
        raise ValueError(f"{source} must contain integers from 1 to 3") from exc
    if stage < 1 or stage > 3:
        raise ValueError(f"{source} must contain integers from 1 to 3")
    return stage


def get_run_stages(config):
    configured_stages = deep_get(config, ["pipeline", "run_stages"], None)
    if configured_stages is not None:
        if not isinstance(configured_stages, list):
            raise ValueError("pipeline.run_stages must be a list like [1, 2, 3]")
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

    run_until_stage = deep_get(config, ["pipeline", "run_until_stage"], 3)
    try:
        run_until_stage = int(run_until_stage)
    except (TypeError, ValueError) as exc:
        raise ValueError("pipeline.run_until_stage must be an integer from 0 to 3") from exc
    if run_until_stage < 0 or run_until_stage > 3:
        raise ValueError("pipeline.run_until_stage must be an integer from 0 to 3")
    return list(range(1, run_until_stage + 1))


def choose_cli_or_config(cli_value, config, key_path, default):
    if cli_value:
        return cli_value
    return deep_get(config, key_path, default)


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


def run_subprocess_step(name, command, dry_run=False):
    print("=" * 80)
    print(f"[{name}]")
    print(command_text(command))
    if dry_run:
        return

    completed = subprocess.run(command, cwd=str(REPO_ROOT))
    if completed.returncode != 0:
        raise SystemExit(f"{name} failed with exit code {completed.returncode}")


def main():
    args = parse_args()
    config_path_obj = Path(args.config).expanduser().resolve()
    config = load_config(config_path_obj)
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

    stage_02 = [
        blender_executable,
        "--background",
        "--python",
        str(SCRIPT_DIR / "02_blender_render.py"),
        "--",
        "--config",
        config_path,
    ]
    stage_03 = [
        python_executable,
        str(SCRIPT_DIR / "03_gs_train.py"),
        "--config",
        config_path,
    ]

    print("=" * 80)
    print(f"[Run stages] requested stages: {run_stages}")
    print(f"[Config] {config_path}")

    stage_actions = {
        1: lambda: run_python_script_in_current_process(
            "01_draped_garments",
            SCRIPT_DIR / "01_clo_make_dataset.py",
            config_path,
            args.dry_run,
        ),
        2: lambda: run_subprocess_step("02_blender_multiview", stage_02, args.dry_run),
        3: lambda: run_subprocess_step("03_3dgs", stage_03, args.dry_run),
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
