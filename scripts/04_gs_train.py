import argparse
import concurrent.futures
import json
import shutil
import subprocess
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
DEFAULT_CONFIG_PATH = Path(r"/home/work/metownsplat-data/kkm/Garment-Material-CLO-dataset/dataset_config.json")


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


def require_config_value(config, keys):
    value = deep_get(config, keys, "")
    if value in (None, ""):
        raise ValueError(f"{'.'.join(keys)} is required in the config")
    return value


def parse_bool(value, default=False):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def resolve_path(value, base_dir):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train one Gaussian Splatting model for each Blender multiview sample."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Dataset config JSON path.")
    parser.add_argument(
        "--render_all_samples",
        default=None,
        help="true trains every multiview sample; false trains only sample_index.",
    )
    parser.add_argument("--sample_index", type=int, default=None, help="Sample index when not training all.")
    parser.add_argument(
        "--skip_existing",
        default=None,
        help="true skips samples that already have a point_cloud.ply; false retrains them.",
    )
    parser.add_argument(
        "--parallel_jobs",
        type=int,
        default=None,
        help="Override 3dgs_training.parallel_jobs.",
    )
    parser.add_argument("--dry_run", action="store_true", help="Print commands without running train.py.")
    return parser.parse_args()


def sample_index_from_dir_name(path, fallback):
    prefix = path.name.split("_", 1)[-1] if path.name.startswith("bend_") else path.name
    try:
        return int(prefix)
    except ValueError:
        return fallback


def is_render_sample_dir(path):
    return (
        path.is_dir()
        and (path / "images").is_dir()
        and (path / "sparse").is_dir()
        and (path / "sparse" / "0" / "cameras.txt").exists()
        and (path / "sparse" / "0" / "images.txt").exists()
    )


def discover_render_targets(render_root, gs_root):
    if not render_root.exists():
        raise FileNotFoundError(f"Render root not found: {render_root}")

    targets = []
    for image_dir in sorted(render_root.rglob("images")):
        source_dir = image_dir.parent
        if not is_render_sample_dir(source_dir):
            continue
        rel_dir = source_dir.relative_to(render_root)
        targets.append(
            {
                "sample_index": sample_index_from_dir_name(source_dir, len(targets)),
                "sample_name": "__".join(rel_dir.parts),
                "source_dir": source_dir,
                "output_dir": gs_root / rel_dir,
            }
        )

    if not targets:
        raise RuntimeError(f"No render samples with images and sparse/0 found in {render_root}")
    return targets


def find_latest_point_cloud(output_dir):
    direct = output_dir / "point_cloud.ply"
    if direct.exists():
        return direct

    candidates = sorted(
        output_dir.glob("point_cloud/iteration_*/point_cloud.ply"),
        key=lambda path: path.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def find_latest_render_dir(output_dir):
    candidates = sorted(
        output_dir.glob("train/ours_*/renders"),
        key=lambda path: path.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def write_summary(path, summary):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)


def clamp_parallel_jobs(value):
    try:
        jobs = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("3dgs_training.parallel_jobs must be an integer >= 1") from exc
    if jobs < 1:
        raise ValueError("3dgs_training.parallel_jobs must be >= 1")
    return jobs


def has_arg(args, option):
    return option in args or any(arg.startswith(f"{option}=") for arg in args)


def train_args_for_target(train_extra_args, target_offset, port_start):
    args = list(train_extra_args)
    if port_start and not has_arg(args, "--port"):
        args.extend(["--port", str(int(port_start) + int(target_offset))])
    return args


def tail_text(path, max_lines=40):
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return "".join(lines[-max_lines:]).strip()


def run_logged_command(command, cwd, log_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
        log_file.write("$ " + " ".join(command) + "\n\n")
        log_file.flush()
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    if completed.returncode != 0:
        recent_log = tail_text(log_path)
        message = (
            f"Command failed with exit code {completed.returncode}: {' '.join(command)}\n"
            f"Log: {log_path}"
        )
        if recent_log:
            message += f"\n\nLast log lines:\n{recent_log}"
        raise RuntimeError(message)


def existing_training_result(target):
    output_dir = target["output_dir"].resolve()
    point_cloud = find_latest_point_cloud(output_dir)
    if not point_cloud:
        return None

    result = {
        "status": "skipped_existing",
        "source_dir": str(target["source_dir"].resolve()),
        "output_dir": str(output_dir),
        "point_cloud_ply": str(point_cloud),
    }

    render_dir = find_latest_render_dir(output_dir)
    if render_dir:
        result["render_dir"] = str(render_dir)

    return result


def render_preview(target, gs_repo, python_executable, render_extra_args, dry_run):
    render_py = gs_repo / "render.py"
    if not render_py.exists():
        raise FileNotFoundError(f"Gaussian Splatting render.py not found: {render_py}")

    output_dir = target["output_dir"].resolve()
    log_path = output_dir / "render.log"
    command = [
        python_executable,
        "render.py",
        "-m",
        str(output_dir),
        "--skip_test",
        *render_extra_args,
    ]

    print(f"  render : {' '.join(command)}")

    if dry_run:
        return {
            "render_status": "dry_run",
            "render_command": command,
            "render_log": str(log_path),
        }

    run_logged_command(command, gs_repo, log_path)

    render_dir = find_latest_render_dir(output_dir)
    if not render_dir:
        raise FileNotFoundError(f"Rendered images were not produced under {output_dir}/train")

    return {
        "render_status": "success",
        "render_command": command,
        "render_log": str(log_path),
        "render_dir": str(render_dir),
    }


def train_one(
    target,
    gs_repo,
    python_executable,
    train_extra_args,
    render_after_train,
    render_extra_args,
    dry_run,
):
    train_py = gs_repo / "train.py"
    if not train_py.exists():
        raise FileNotFoundError(f"Gaussian Splatting train.py not found: {train_py}")

    source_dir = target["source_dir"].resolve()
    output_dir = target["output_dir"].resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "train.log"

    command = [
        python_executable,
        "train.py",
        "-s",
        str(source_dir),
        "-m",
        str(output_dir),
        *train_extra_args,
    ]

    print("=" * 80)
    print(f"[3DGS] {target['sample_name']}")
    print(f"  source : {source_dir}")
    print(f"  output : {output_dir}")
    print(f"  cmd    : {' '.join(command)}")

    if dry_run:
        result = {
            "status": "dry_run",
            "command": command,
            "source_dir": str(source_dir),
            "output_dir": str(output_dir),
            "train_log": str(log_path),
            "point_cloud_ply": "",
        }
        if render_after_train:
            result.update(
                render_preview(
                    target,
                    gs_repo,
                    python_executable,
                    render_extra_args,
                    dry_run=True,
                )
            )
        return result

    run_logged_command(command, gs_repo, log_path)

    point_cloud = find_latest_point_cloud(output_dir)
    if not point_cloud:
        raise FileNotFoundError(f"point_cloud.ply was not produced under {output_dir}")

    final_point_cloud = output_dir / "point_cloud.ply"
    if point_cloud != final_point_cloud:
        shutil.copy2(point_cloud, final_point_cloud)
        point_cloud = final_point_cloud

    result = {
        "status": "success",
        "command": command,
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "train_log": str(log_path),
        "point_cloud_ply": str(point_cloud),
    }
    if render_after_train:
        result.update(
            render_preview(
                target,
                gs_repo,
                python_executable,
                render_extra_args,
                dry_run=False,
            )
        )
    return result


def run_target(
    target,
    target_offset,
    skip_existing,
    gs_repo,
    python_executable,
    train_extra_args,
    port_start,
    render_after_train,
    render_extra_args,
    dry_run,
):
    result = existing_training_result(target) if skip_existing else None
    if result:
        print("=" * 80)
        print(f"[Skip] {target['sample_name']}")
        print(f"  output : {result['output_dir']}")
        print(f"  point  : {result['point_cloud_ply']}")
        return result

    target_train_args = train_args_for_target(train_extra_args, target_offset, port_start)
    return train_one(
        target,
        gs_repo,
        python_executable,
        target_train_args,
        render_after_train,
        render_extra_args,
        dry_run,
    )


def main():
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    config_dir = config_path.parent

    output_root = (
        deep_get(config, ["project", "output_dir"])
        or deep_get(config, ["project", "dataset_root"])
        or ""
    )
    if not output_root:
        raise ValueError("project.output_dir is required")

    output_root = resolve_path(output_root, config_dir)
    render_root = output_root / require_config_value(config, ["naming", "render_dir"])
    gs_root = output_root / require_config_value(config, ["naming", "gs_dir"])

    gs_repo_value = deep_get(config, ["3dgs_training", "gaussian_splatting_dir"], "")
    if not gs_repo_value:
        raise ValueError("3dgs_training.gaussian_splatting_dir is required")
    gs_repo = resolve_path(gs_repo_value, config_dir)

    python_executable = deep_get(config, ["3dgs_training", "python_executable"], "python")
    train_extra_args = deep_get(config, ["3dgs_training", "extra_args"], [])
    if not isinstance(train_extra_args, list):
        raise TypeError("3dgs_training.extra_args must be a list")
    train_extra_args = [str(value) for value in train_extra_args]

    render_after_train = parse_bool(deep_get(config, ["3dgs_training", "render_after_train"], True), True)
    render_extra_args = deep_get(config, ["3dgs_training", "render_extra_args"], [])
    if not isinstance(render_extra_args, list):
        raise TypeError("3dgs_training.render_extra_args must be a list")
    render_extra_args = [str(value) for value in render_extra_args]
    skip_existing = parse_bool(
        args.skip_existing,
        parse_bool(deep_get(config, ["3dgs_training", "skip_existing"], True), True),
    )
    parallel_jobs = clamp_parallel_jobs(
        args.parallel_jobs
        if args.parallel_jobs is not None
        else deep_get(config, ["3dgs_training", "parallel_jobs"], 1)
    )
    port_start = int(deep_get(config, ["3dgs_training", "port_start"], 6009))

    render_all_samples = parse_bool(
        args.render_all_samples,
        parse_bool(deep_get(config, ["3dgs_training", "render_all_samples"], True), True),
    )
    sample_index = (
        args.sample_index
        if args.sample_index is not None
        else int(deep_get(config, ["3dgs_training", "sample_index"], 0))
    )

    targets = discover_render_targets(render_root, gs_root)
    if not render_all_samples:
        matches = [target for target in targets if target["sample_index"] == sample_index]
        if not matches:
            raise RuntimeError(f"No render sample matched sample_index={sample_index}")
        targets = matches[:1]

    pipeline_summary_path = gs_root / "pipeline_summary.json"
    pipeline_summary = {
        "gaussian_splatting_dir": str(gs_repo),
        "render_root": str(render_root),
        "gs_root": str(gs_root),
        "render_all_samples": render_all_samples,
        "num_targets": len(targets),
        "dry_run": args.dry_run,
        "skip_existing": skip_existing,
        "render_after_train": render_after_train,
        "parallel_jobs": parallel_jobs,
        "port_start": port_start,
        "samples": [],
    }
    write_summary(pipeline_summary_path, pipeline_summary)

    records_by_target = {}
    for target in targets:
        record = {
            "sample_index": target["sample_index"],
            "sample_name": target["sample_name"],
            "source_dir": str(target["source_dir"]),
            "output_dir": str(target["output_dir"]),
            "status": "queued",
        }
        pipeline_summary["samples"].append(record)
        records_by_target[id(target)] = record
    write_summary(pipeline_summary_path, pipeline_summary)

    print(f"[3DGS] targets: {len(targets)}")
    print(f"[3DGS] parallel_jobs: {parallel_jobs}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_jobs) as executor:
        future_to_target = {}
        for target_offset, target in enumerate(targets):
            record = records_by_target[id(target)]
            record["status"] = "started"
            write_summary(pipeline_summary_path, pipeline_summary)
            future = executor.submit(
                run_target,
                target,
                target_offset,
                skip_existing,
                gs_repo,
                python_executable,
                train_extra_args,
                port_start,
                render_after_train,
                render_extra_args,
                args.dry_run,
            )
            future_to_target[future] = target

        for future in concurrent.futures.as_completed(future_to_target):
            target = future_to_target[future]
            record = records_by_target[id(target)]
            try:
                record.update(future.result())
            except Exception as exc:
                record.update({"status": "failed", "error": str(exc)})
                write_summary(pipeline_summary_path, pipeline_summary)
                for pending in future_to_target:
                    pending.cancel()
                raise
            write_summary(pipeline_summary_path, pipeline_summary)

    print("[Done] 3DGS targets:", len(targets))
    print("[Done] Pipeline summary:", pipeline_summary_path)


if __name__ == "__main__":
    main()
