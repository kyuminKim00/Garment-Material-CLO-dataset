import argparse
import json
import runpy
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(r"C:\Users\CGnA\Desktop\CLO")
SCRIPT_DIR = REPO_ROOT / "scripts"
CONFIG_JSON_PATH = r"C:\Users\CGnA\Desktop\CLO\dataset_config.json"


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run dataset stages up to pipeline.run_until_stage from config. "
            "Paste/run this inside CLO Python for stages 01 and 02; "
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
    return parser.parse_args()


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


def get_run_until_stage(config):
    stage = deep_get(config, ["pipeline", "run_until_stage"], 3)
    try:
        stage = int(stage)
    except (TypeError, ValueError) as exc:
        raise ValueError("pipeline.run_until_stage must be an integer from 0 to 4") from exc
    if stage < 0 or stage > 4:
        raise ValueError("pipeline.run_until_stage must be an integer from 0 to 4")
    return stage


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
    run_until_stage = get_run_until_stage(config)
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
        str(SCRIPT_DIR / "03_blender_render.py"),
        "--",
        "--config",
        config_path,
    ]
    stage_04 = [
        python_executable,
        str(SCRIPT_DIR / "04_gs_train.py"),
        "--config",
        config_path,
    ]

    print("=" * 80)
    print(f"[Run stages] requested through stage {run_until_stage}")
    print(f"[Config] {config_path}")

    if run_until_stage >= 1:
        run_python_script_in_current_process(
            "01_fabric_bending",
            SCRIPT_DIR / "01_clo_fab_sampler.py",
            config_path,
            args.dry_run,
        )
    if run_until_stage >= 2:
        run_python_script_in_current_process(
            "02_draped_garments",
            SCRIPT_DIR / "02_clo_make_dataset.py",
            config_path,
            args.dry_run,
        )
    if run_until_stage >= 3:
        run_subprocess_step("03_blender_multiview", stage_03, args.dry_run)
    if run_until_stage >= 4:
        run_subprocess_step("04_3dgs", stage_04, args.dry_run)

    print("=" * 80)
    if run_until_stage == 0:
        print("[Done] no dataset stages were run")
    else:
        print(f"[Done] stages 01 through {run_until_stage:02d} completed")


if __name__ == "__main__":
    main()
