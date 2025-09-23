from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import click
from typing_extensions import Never

import wandb
from wandb.env import error_reporting_enabled, is_debug
from wandb.sdk import wandb_setup
from wandb.util import get_core_path

from .beta_sync import _find_wandb_files


def _fatal(message: str) -> Never:
    """Print an error message and exit with code 1."""
    click.echo(f"Error: {message}", err=True)
    sys.exit(1)


def _wandb_file_path(path: str | None) -> str:
    """Returns absolute path to the .wandb file to display with LEET.

    If `path` is not provided, looks for the latest W&B run.

    Prints an error and exits if a valid path is not found.
    """
    if not path:
        wandb_dir = wandb_setup.singleton().settings.wandb_dir

        wandb_run_path = (pathlib.Path(wandb_dir) / "latest-run").resolve()
    else:
        wandb_run_path = pathlib.Path(path).resolve()

    wandb_files = list(_find_wandb_files(wandb_run_path, skip_synced=False))

    if len(wandb_files) == 0:
        _fatal(f"Could not find a .wandb file in {wandb_run_path}.")
    elif len(wandb_files) > 1:
        _fatal(f"Found multiple .wandb files in {wandb_run_path}.")

    return wandb_files[0]


def launch(path: str | None) -> Never:
    wandb._sentry.configure_scope(process_context="leet")

    wandb_file = _wandb_file_path(path)

    try:
        core_path = get_core_path()

        args = [core_path, "leet"]
        args.append(wandb_file)

        if not error_reporting_enabled():
            args.append("--no-observability")

        if is_debug(default="False"):
            args.extend(["--log-level", "-4"])

        result = subprocess.run(
            args,
            env=os.environ,
            close_fds=True,
        )
        sys.exit(result.returncode)

    except Exception as e:
        wandb._sentry.reraise(e)
