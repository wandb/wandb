from __future__ import annotations

import dataclasses
import os
import pathlib
import subprocess
import sys
import urllib.parse

import click
from typing_extensions import Never

from wandb import util
from wandb.analytics import get_sentry
from wandb.env import error_reporting_enabled, is_debug
from wandb.sdk import wandb_setup
from wandb.sdk.lib import wbauth
from wandb.util import get_core_path


class LaunchConfig:
    """Configuration for launching LEET."""


@dataclasses.dataclass(frozen=True)
class LocalLaunchConfig(LaunchConfig):
    """Configuration for launching LEET."""

    wandb_dir: str
    run_file: str | None = None


@dataclasses.dataclass(frozen=True)
class RemoteLaunchConfig(LaunchConfig):
    """Configuration for launching LEET."""

    base_url: str
    project: str
    entity: str
    api_key: str
    run_id: str | None = None


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
        return LocalLaunchConfig(wandb_dir=str(wandb_dir))

    resolved = pathlib.Path(path).resolve()

    if resolved.is_file():
        if resolved.suffix == ".wandb":
            run_dir = resolved.parent
            wandb_dir = run_dir.parent
            return LocalLaunchConfig(wandb_dir=str(wandb_dir), run_file=str(resolved))
        else:
            _fatal(f"Not a .wandb file: {resolved}")

    if resolved.is_dir():
        wandb_file = _find_wandb_file_in_dir(resolved)
        if wandb_file:
            wandb_dir = resolved.parent
            return LocalLaunchConfig(wandb_dir=str(wandb_dir), run_file=str(wandb_file))
        else:
            return LocalLaunchConfig(wandb_dir=str(resolved))

    _fatal(f"Path does not exist: {resolved}")


def _base_args() -> list[str]:
    """Build the common base arguments for wandb-core leet commands."""
    args = [get_core_path(), "leet"]

    if not error_reporting_enabled():
        args.append("--no-observability")

    if is_debug(default="False"):
        args.extend(["--log-level", "-4"])

    return args


def _run_core(args: list[str], env: dict[str, str] | None = None) -> Never:
    """Run wandb-core with the given arguments and exit with its return code."""
    try:
        result = subprocess.run(args, env=env, close_fds=True)
        sys.exit(result.returncode)
    except Exception as e:
        get_sentry().reraise(e)


def launch(path: str | None, pprof: str) -> Never:
    """Launch the LEET TUI."""
    get_sentry().configure_scope(process_context="leet")

    if path is not None and (path.startswith("https://") or path.startswith("http://")):
        config = _create_remote_launch_config(path)
    else:
        config = _resolve_path(path)

    args = _base_args()
    env = os.environ.copy()

    if pprof:
        args.extend(["--pprof", pprof])

    if isinstance(config, LocalLaunchConfig):
        args.extend(_get_local_launch_args(config))
    elif isinstance(config, RemoteLaunchConfig):
        args.extend(_get_remote_launch_args(config))

        # Set api key so it is not visible in the process tree
        env["WANDB_API_KEY"] = config.api_key

    _run_core(args, env)


def launch_config() -> Never:
    """Launch the LEET configuration editor."""
    get_sentry().configure_scope(process_context="leet-config")

    args = _base_args()
    args.append("--config")

    _run_core(args)


def _get_local_launch_args(config: LocalLaunchConfig) -> list[str]:
    """Get the arguments for launching LEET locally."""
    args = []
    if config.run_file:
        args.extend(["--run-file", config.run_file])
    args.append(config.wandb_dir)
    return args


def _get_remote_launch_args(config: RemoteLaunchConfig) -> list[str]:
    """Get the arguments for launching LEET remotely."""
    args = []
    args.extend(
        [
            "--base-url",
            config.base_url,
            "--project",
            config.project,
            "--entity",
            config.entity,
        ]
    )
    if config.run_id:
        args.extend(["--run-id", config.run_id])

    # TODO: what args do we need for remote launch?
    return args


def _create_remote_launch_config(path: str) -> RemoteLaunchConfig:
    """Create a LEET launch configuration for a remote run."""
    parsed_url = urllib.parse.urlparse(path)
    entity, project, run_id = util.parse_path(parsed_url.path, None, None)

    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    if parsed_url.netloc == "wandb.ai":
        base_url = "https://api.wandb.ai"

    auth = wbauth.authenticate_session(
        host=base_url,
        source="wandb-cli",
        no_offline=True,
        input_timeout=wandb_setup.singleton().settings.login_timeout,
    )
    assert isinstance(auth, wbauth.AuthApiKey)

    return RemoteLaunchConfig(
        base_url=base_url,
        project=project,
        entity=entity,
        api_key=auth.api_key,
        run_id=run_id,
    )
