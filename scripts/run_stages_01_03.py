import argparse
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
            "Run dataset stages 01, 02, and 03 in order. "
            "Paste/run this inside CLO Python for stages 01 and 02; "
            "stage 03 launches Blender in background mode."
        )
    )
    parser.add_argument(
        "--config",
        default=CONFIG_JSON_PATH,
        help="Dataset config JSON path.",
    )
    parser.add_argument(
        "--blender",
        default="blender",
        help="Blender executable for stage 03 rendering.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without running them.",
    )
    return parser.parse_args()


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
    config_path = str(Path(args.config).expanduser().resolve())

    stage_03 = [
        args.blender,
        "--background",
        "--python",
        str(SCRIPT_DIR / "blender_render.py"),
        "--",
        "--config",
        config_path,
    ]

    run_python_script_in_current_process(
        "01_fabric_bending",
        SCRIPT_DIR / "clo_fab_sampler.py",
        config_path,
        args.dry_run,
    )
    run_python_script_in_current_process(
        "02_draped_garments",
        SCRIPT_DIR / "clo_make_dataset.py",
        config_path,
        args.dry_run,
    )
    run_subprocess_step("03_blender_multiview", stage_03, args.dry_run)

    print("=" * 80)
    print("[Done] stages 01, 02, and 03 completed")


if __name__ == "__main__":
    main()
