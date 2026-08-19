#!/usr/bin/env python3
"""Capture a real offline `.wandb` log for compat testing.

This script installs a specific wandb version in a throwaway venv, runs a tiny
offline logging script, and writes fixture artifacts under:

tests/assets/compat_logs/captured/offline-run-<fixture-name>/
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import venv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CAPTURED_ROOT = Path("tests/assets/compat_logs/captured")
CAPTURE_SCRIPT = Path("tools/compat_log_capture_scripts/offline_basic.py")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wandb-version",
        required=True,
        help="Exact wandb version to install (for example: 0.28.1).",
    )
    parser.add_argument(
        "--label",
        default="",
        help="Optional fixture suffix (for example: pre-core).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow overwriting existing fixture files.",
    )
    return parser.parse_args()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")


def fixture_name_for(version: str, label: str) -> str:
    version_slug = slugify(version.replace(".", "-"))
    name = f"wandb-{version_slug}"
    if label:
        name = f"{name}-{slugify(label)}"
    return name


@dataclass(frozen=True)
class OutputPaths:
    fixture_dir: Path
    wandb_path: Path
    generate_script_path: Path
    metadata_path: Path


def build_output_paths(fixture_name: str) -> OutputPaths:
    fixture_dir = CAPTURED_ROOT / f"offline-run-{fixture_name}"
    return OutputPaths(
        fixture_dir=fixture_dir,
        wandb_path=fixture_dir / f"run-{fixture_name}.wandb",
        generate_script_path=fixture_dir / f"generate-{fixture_name}.py",
        metadata_path=fixture_dir / f"metadata-{fixture_name}.json",
    )


def assert_not_overwriting(paths: OutputPaths, force: bool) -> None:
    conflicts = [
        path
        for path in (
            paths.wandb_path,
            paths.generate_script_path,
            paths.metadata_path,
        )
        if path.exists()
    ]
    if not conflicts or force:
        return

    lines = [
        "!!! REFUSING TO OVERWRITE EXISTING CAPTURED FIXTURE FILES !!!",
        "The following paths already exist:",
    ]
    lines.extend(f"  - {path}" for path in conflicts)
    lines.append("Re-run with --force only if you intentionally want to replace them.")
    raise SystemExit("\n".join(lines))


def _run(command: list[str], env: dict[str, str] | None = None, cwd: Path | None = None) -> None:
    subprocess.run(command, check=True, env=env, cwd=cwd)


def main() -> int:
    args = parse_args()
    fixture_name = fixture_name_for(args.wandb_version, args.label)
    output_paths = build_output_paths(fixture_name)
    assert_not_overwriting(output_paths, force=args.force)

    output_paths.fixture_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="wandb-compat-capture-") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        venv_dir = tmpdir / "venv"
        script_path = tmpdir / "generate.py"
        result_path = tmpdir / "result.json"

        venv.EnvBuilder(with_pip=True).create(venv_dir)
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        python_bin = venv_dir / bin_dir / "python"
        pip_bin = venv_dir / bin_dir / "pip"

        _run([str(pip_bin), "install", "--upgrade", "pip"])
        _run([str(pip_bin), "install", f"wandb=={args.wandb_version}"])

        generator_source = CAPTURE_SCRIPT.read_text(encoding="utf-8")

        script_path.write_text(generator_source, encoding="utf-8")
        run_env = os.environ.copy()
        run_env["CAPTURE_FIXTURE_NAME"] = fixture_name
        run_env["CAPTURE_RESULT_PATH"] = str(result_path)
        _run([str(python_bin), str(script_path)], env=run_env, cwd=tmpdir)

        result = json.loads(result_path.read_text(encoding="utf-8"))
        run_dir = Path(result["run_dir"])
        wandb_files = list(run_dir.glob("run-*.wandb"))
        if len(wandb_files) != 1:
            raise RuntimeError(
                f"expected exactly 1 .wandb file in {run_dir}, found {len(wandb_files)}"
            )

        shutil.copy2(wandb_files[0], output_paths.wandb_path)
        output_paths.generate_script_path.write_text(generator_source, encoding="utf-8")

        metadata = {
            "fixture_name": fixture_name,
            "label": args.label,
            "requested_wandb_version": args.wandb_version,
            "installed_wandb_version": result["wandb_version"],
            "python_version": result["python_version"],
            "platform": platform.platform(),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "script_args": vars(args),
            "source_wandb_file": str(wandb_files[0]),
            "captured_wandb_file": str(output_paths.wandb_path),
            "run_dir": str(run_dir),
            "run_id": fixture_name,
        }
        output_paths.metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(f"Captured fixture: {fixture_name}")
    print(f"  - {output_paths.wandb_path}")
    print(f"  - {output_paths.generate_script_path}")
    print(f"  - {output_paths.metadata_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"command failed (exit {exc.returncode}): {' '.join(exc.cmd)}"
        ) from exc
