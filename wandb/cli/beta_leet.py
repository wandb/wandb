from __future__ import annotations

import dataclasses
import os
import pathlib
import subprocess
import sys

import click
from typing_extensions import Never

from wandb.analytics import get_sentry
from wandb.env import error_reporting_enabled, is_debug
from wandb.sdk import wandb_setup
from wandb.util import get_core_path


@dataclasses.dataclass(frozen=True)
class LaunchConfig:
    """Configuration for launching LEET."""

    wandb_dir: str
    run_file: str | None = None


def _fatal(message: str) -> Never:
    """Print an error message and exit with code 1."""
    click.echo(f"Error: {message}", err=True)
    sys.exit(1)


def _find_wandb_file_in_dir(dir_path: pathlib.Path) -> pathlib.Path | None:
    """Find a run-*.wandb file in the given directory.

    Returns None if not found or multiple found.
    """
    wandb_files = list(dir_path.glob("run-*.wandb"))
    if len(wandb_files) == 1:
        return wandb_files[0]
    return None


def _resolve_path(path: str | None) -> LaunchConfig:
    """Resolve the given path into a LaunchConfig.

    Behavior:
        - No path: Use default wandb_dir (workspace mode)
        - .wandb file: Parent's parent as wandb_dir, file as run_file
        - Run directory: Parent as wandb_dir, found .wandb as run_file
        - Other directory: Treat as wandb_dir (workspace mode)
    """
    if not path:
        wandb_dir = wandb_setup.singleton().settings.wandb_dir
        return LaunchConfig(wandb_dir=str(wandb_dir))

    resolved = pathlib.Path(path).resolve()

    if resolved.is_file():
        if resolved.suffix == ".wandb":
            run_dir = resolved.parent
            wandb_dir = run_dir.parent
            return LaunchConfig(wandb_dir=str(wandb_dir), run_file=str(resolved))
        else:
            _fatal(f"Not a .wandb file: {resolved}")

    if resolved.is_dir():
        wandb_file = _find_wandb_file_in_dir(resolved)
        if wandb_file:
            wandb_dir = resolved.parent
            return LaunchConfig(wandb_dir=str(wandb_dir), run_file=str(wandb_file))
        else:
            return LaunchConfig(wandb_dir=str(resolved))

    _fatal(f"Path does not exist: {resolved}")


def _base_args() -> list[str]:
    """Build the common base arguments for wandb-core leet commands."""
    args = [get_core_path(), "leet"]

    if not error_reporting_enabled():
        args.append("--no-observability")

    if is_debug(default="False"):
        args.extend(["--log-level", "-4"])

    return args


def _run_core(args: list[str]) -> Never:
    """Run wandb-core with the given arguments and exit with its return code."""
    try:
        result = subprocess.run(args, env=os.environ, close_fds=True)
        sys.exit(result.returncode)
    except Exception as e:
        get_sentry().reraise(e)


def launch(path: str | None, pprof: str) -> Never:
    """Launch the LEET TUI."""
    get_sentry().configure_scope(process_context="leet")

    config = _resolve_path(path)
    args = _base_args()

    if config.run_file:
        args.extend(["--run-file", config.run_file])

    if pprof:
        args.extend(["--pprof", pprof])

    args.append(config.wandb_dir)

    _run_core(args)


def launch_config() -> Never:
    """Launch the LEET configuration editor."""
    get_sentry().configure_scope(process_context="leet-config")

    args = _base_args()
    args.append("--config")

    _run_core(args)
