"""The `wandb leet` command.

W&B LEET, the Lightweight Experiment Exploration Tool, is a terminal UI
for viewing W&B runs.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import subprocess
import sys
import urllib.parse
from typing import Any

import click
from typing_extensions import Never

from wandb.analytics import get_sentry
from wandb.env import error_reporting_enabled, is_debug
from wandb.errors import WandbCoreNotAvailableError
from wandb.sdk import wandb_setup
from wandb.sdk.lib import wbauth
from wandb.util import get_core_path


class DefaultCommandGroup(click.Group):
    """A click Group that falls through to a default command.

    If the first argument isn't a recognized subcommand or a help flag,
    the default command is invoked with all arguments passed through.
    This allows backward-compatible CLIs where `cmd [path]` and
    `cmd run [path]` are equivalent.
    """

    def __init__(self, *args: Any, default_cmd: str = "run", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.default_cmd = default_cmd

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args and args[0] in ctx.help_option_names:
            return super().parse_args(ctx, args)
        if not args or args[0].startswith("-") or args[0] not in self.commands:
            args = [self.default_cmd, *args]
        return super().parse_args(ctx, args)

    def format_usage(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write_usage(ctx.command_path, "[PATH] | COMMAND [ARGS]...")


@click.group(
    cls=DefaultCommandGroup,
    default_cmd="run",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def leet() -> None:
    """W&B LEET: the Lightweight Experiment Exploration Tool.

    A terminal UI for viewing your W&B runs locally.

    \b
    Examples:
        wandb leet                    View the latest run
        wandb leet ./wandb            Browse runs in a wandb directory
        wandb leet <run-url>          View a remote W&B run
        wandb leet symon              View live local system metrics
    """  # noqa: D301 -- the \b escape is click's marker to not rewrap Examples.


@leet.command()
@click.argument("path", nargs=1, type=click.STRING, required=False)
@click.option(
    "--pprof",
    default="",
    hidden=True,
    help="Serve /debug/pprof/* on this address (e.g. 127.0.0.1:6060).",
)
@click.help_option("-h", "--help")
def run(path: str | None = None, pprof: str = "") -> None:
    """Launch the LEET TUI.

    LEET is a terminal UI for viewing a W&B run specified by an optional PATH.

    PATH can include a .wandb file, a run directory containing a .wandb file,
    or a W&B run URL.
    If PATH is not provided, the command will look for the latest run.
    """
    launch(path, pprof)


@leet.command()
@click.option(
    "--pprof",
    default="",
    hidden=True,
    help="Serve /debug/pprof/* on this address (e.g. 127.0.0.1:6060).",
)
@click.option(
    "--interval",
    default="",
    metavar="DURATION",
    help="Sampling interval for system metrics (e.g. 500ms, 2s, 1m).",
)
@click.help_option("-h", "--help")
def symon(pprof: str = "", interval: str = "") -> None:
    """Launch the standalone system monitor."""
    launch_symon(pprof=pprof, interval=interval)


@leet.command()
def config() -> None:
    """Edit LEET configuration."""
    launch_config()


class LaunchConfig:
    """Configuration for launching LEET."""


@dataclasses.dataclass(frozen=True)
class LocalLaunchConfig(LaunchConfig):
    """Configuration for launching LEET."""

    wandb_dir: str
    run_file: str | None = None


@dataclasses.dataclass(frozen=True)
class RemoteLaunchConfig(LaunchConfig):
    """Configuration for launching LEET against a remote run.

    The URL is the single source of truth: it is parsed here for early
    validation and host canonicalization, and again by wandb-core to
    derive the entity, project, and run ID.
    """

    remote_url: str
    api_key: str


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
    try:
        core_path = get_core_path()
    except WandbCoreNotAvailableError as e:
        get_sentry().exception(f"using `wandb leet`. failed with {e}")
        _fatal(str(e))

    args = [core_path, "leet"]

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


def launch_symon(pprof: str = "", interval: str = "") -> Never:
    """Launch the standalone system monitor."""
    get_sentry().configure_scope(process_context="leet-symon")

    args = _base_args()
    args.append("--symon")

    if pprof:
        args.extend(["--pprof", pprof])

    if interval:
        args.extend(["--interval", interval])

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
    return ["--remote-url", config.remote_url]


def _create_remote_launch_config(path: str) -> RemoteLaunchConfig:
    """Create a LEET launch configuration for a remote run."""
    base_url, remote_url = _parse_remote_url(path)

    auth = wbauth.authenticate_session(
        host=base_url,
        source="wandb-cli",
        no_offline=True,
        input_timeout=wandb_setup.singleton().settings.login_timeout,
    )
    if not isinstance(auth, wbauth.AuthApiKey):
        _fatal("LEET remote runs require API key authentication.")

    return RemoteLaunchConfig(remote_url=remote_url, api_key=auth.api_key)


def _parse_remote_url(path: str) -> tuple[str, str]:
    """Validate a W&B run URL and return (base_url, canonical_url).

    Canonicalization rewrites the wandb.ai host to api.wandb.ai and drops
    any query string or fragment.
    """
    parsed_url = urllib.parse.urlparse(path)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        _fatal(
            f"Invalid remote URL: {path!r}."
            " Expected format: https://<host>/<entity>/<project>/runs/<run_id>"
        )

    parts = parsed_url.path.strip("/").split("/")
    if len(parts) == 4 and parts[2] == "runs":
        parts = [parts[0], parts[1], parts[3]]
    if len(parts) != 3 or not all(parts):
        _fatal(
            f"Invalid remote URL: {path!r}."
            " Expected format: https://<host>/<entity>/<project>/runs/<run_id>"
        )

    netloc = "api.wandb.ai" if parsed_url.netloc == "wandb.ai" else parsed_url.netloc
    base_url = f"{parsed_url.scheme}://{netloc}"
    return base_url, f"{base_url}{parsed_url.path}"
