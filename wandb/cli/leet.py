"""The `wandb leet` command.

W&B LEET, the Lightweight Experiment Exploration Tool, is a terminal UI
for viewing W&B runs.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse
from typing import Any

import click
from typing_extensions import Never

from wandb.analytics import get_telemetry_recorder
from wandb.env import error_reporting_enabled, is_debug
from wandb.errors import AuthenticationError, UsageError, WandbCoreNotAvailableError
from wandb.sdk import wandb_setup
from wandb.sdk.lib import urls, wbauth
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


class ScriptCommand(click.Command):
    """A click Command whose usage errors are one line of JSON on stderr."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except click.UsageError as e:
            _fatal_json("bad_request", e.format_message())


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
        wandb leet <project-url>      Browse a remote W&B project
        wandb leet <run-url>          View a remote W&B run
        wandb leet symon              View live local system metrics
        wandb leet inspect [PATH]     Browse the raw records in a .wandb log
        wandb leet inspect --summary  Print the latest run's state and metrics
        wandb leet runs [PATH]        List the runs of a directory or project as JSON
        wandb leet history --keys K   Print a run's metric series as JSON
        wandb leet summary [PATH]     Print a run's state, metrics and console as JSON
        wandb leet console --last 50  Print the last console lines of a run as JSON
        wandb leet summary <run-url>  The same for a run on the W&B server
        wandb leet system --bins 60   Print a run's system metrics as JSON
        wandb leet session status     Steer the LEET open on a wandb directory
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
    or a W&B project/run URL.
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
@click.argument("path", nargs=1, type=click.STRING, required=False)
@click.option(
    "--summary",
    is_flag=True,
    help="Print the run's state, latest metric values, config and console"
    " tail instead of its records.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Print JSON: one line per record, or one object with --summary.",
)
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    help="Keep printing records as the run writes them until it exits.",
)
@click.option(
    "--idle-timeout",
    default="",
    metavar="DURATION",
    help="With --follow, stop once the run's file has gone this long without"
    " a write (e.g. 30s, 1h; 0 waits forever). Defaults to 10m.",
)
@click.help_option("-h", "--help")
def inspect(
    path: str | None = None,
    summary: bool = False,
    json_output: bool = False,
    follow: bool = False,
    idle_timeout: str = "",
) -> None:
    """Inspect a run's .wandb transaction log.

    Opens a browsable list of the records stored in the log next to a
    text view of the selected record. When stdout is not a terminal, or
    with --json or --follow, prints the records instead.

    \b
    Examples:
        wandb leet inspect --summary            State, latest metrics, console tail
        wandb leet inspect --summary --json     The same as one JSON object
        wandb leet inspect --json | grep '"type":"history"' | tail -n 5
        wandb leet inspect --follow --json      Stream records as they are written
        wandb leet inspect run.wandb | less     Browse the records as text

    PATH can be a .wandb file, a run directory containing one, or a
    wandb directory. If PATH is not provided, the latest run is used.
    """  # noqa: D301 -- the \b escape is click's marker to not rewrap Examples.
    launch_inspect(
        path,
        summary=summary,
        json_output=json_output,
        follow=follow,
        idle_timeout=idle_timeout,
    )


@leet.command(cls=ScriptCommand)
@click.argument("path", nargs=1, type=click.STRING, required=False)
@click.option(
    "--filter",
    "filter_",
    default="",
    metavar="QUERY",
    help="List only the runs matching this filter, in the language of the LEET"
    " runs sidebar, e.g. 'name:resnet cfg.lr>=0.001'.",
)
@click.option(
    "--glob",
    is_flag=True,
    help="Match the patterns of --filter as globs instead of regexes.",
)
@click.option(
    "--summary-keys",
    default="",
    metavar="KEYS",
    help="Comma-separated summary keys or globs with * and ? to return per run,"
    " e.g. 'val/loss,train/*', as updated in the last 2 MiB of the file."
    " A glob never matches keys starting with _.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    metavar="N",
    help="Runs to return. Defaults to 200.",
)
@click.help_option("-h", "--help")
def runs(
    path: str | None = None,
    filter_: str = "",
    glob: bool = False,
    summary_keys: str = "",
    limit: int | None = None,
) -> None:
    """List the runs of a wandb directory or a W&B project as JSON.

    Prints one JSON object with the runs newest first: each run's ID, name,
    project, state, exit code, last step, tags and notes, whether it is
    selected or pinned in LEET and, with --summary-keys, its latest summary
    values.

    \b
    Examples:
        wandb leet runs
        wandb leet runs --filter 'cfg.lr>=0.001' --limit 5
        wandb leet runs --summary-keys 'val/loss,train/*'
        wandb leet runs ./wandb/run-20260623_234844-2w7tm747
        wandb leet runs https://wandb.ai/<entity>/<project>

    PATH can be a wandb directory, a run directory or a .wandb file to list
    that one run, or the URL of a W&B project to list its runs from the
    server. If PATH is not provided, the configured wandb directory is used.
    """  # noqa: D301 -- the \b escape is click's marker to not rewrap Examples.
    launch_query(
        "runs",
        path,
        filter=filter_,
        glob=glob,
        summary_keys=summary_keys,
        limit=limit,
    )


@leet.command(cls=ScriptCommand)
@click.argument("path", nargs=1, type=click.STRING, required=False)
@click.option(
    "--run",
    default="",
    metavar="RUN",
    help="The run to read: its directory name, its ID or its display name."
    " Defaults to the newest run.",
)
@click.option(
    "--keys",
    default="",
    metavar="KEYS",
    help="Comma-separated metric keys or globs with * and ?, e.g. 'train/loss,val/*'."
    " A glob never matches keys starting with _.",
)
@click.option(
    "--x-axis",
    default="",
    metavar="KEY",
    help="Key to use as the x axis of every metric instead of its own, e.g. _runtime.",
)
@click.option(
    "--bins",
    type=int,
    default=None,
    metavar="N",
    help="Aggregate each metric into N equal-width bins instead of returning rows.",
)
@click.option(
    "--min-step", type=int, default=None, metavar="N", help="First _step to include."
)
@click.option(
    "--max-step", type=int, default=None, metavar="N", help="Last _step to include."
)
@click.option(
    "--last", type=int, default=None, metavar="N", help="Return only the last N rows."
)
@click.option(
    "--limit",
    type=int,
    default=None,
    metavar="N",
    help="Rows per call. Defaults to 1000.",
)
@click.option(
    "--after",
    default="",
    metavar="CURSOR",
    help="The next_cursor of a previous call, to continue after the rows it returned.",
)
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    help="Keep printing new rows as the run writes them, one JSON object per poll.",
)
@click.option(
    "--idle-timeout",
    default="",
    metavar="DURATION",
    help="With --follow, stop once the run's file has gone this long without"
    " a write (e.g. 30s, 1h; 0 waits forever). Defaults to 10m.",
)
@click.help_option("-h", "--help")
def history(
    path: str | None = None,
    run: str = "",
    keys: str = "",
    x_axis: str = "",
    bins: int | None = None,
    min_step: int | None = None,
    max_step: int | None = None,
    last: int | None = None,
    limit: int | None = None,
    after: str = "",
    follow: bool = False,
    idle_timeout: str = "",
) -> None:
    """Print the metric series of a run as JSON.

    Prints one JSON object with the run's state and the rows of the
    selected metrics, or with --bins their min, max, average and last
    value per bin. When more rows exist than fit in one call, the object
    carries a next_cursor to pass back with --after.

    \b
    Examples:
        wandb leet history --keys 'train/loss,val/*' --bins 200
        wandb leet history --keys train/loss --last 100
        wandb leet history --keys train/loss --min-step 4000 --max-step 4400
        wandb leet history --keys train/loss --last 50 --follow
        wandb leet history ./wandb --run sim-unstable-L32 --keys 'eval/*'

    PATH can be a .wandb file, a run directory containing one, or a
    wandb directory. If PATH is not provided, the configured wandb
    directory is used.
    """  # noqa: D301 -- the \b escape is click's marker to not rewrap Examples.
    launch_query(
        "history",
        path,
        run=run,
        keys=keys,
        x_axis=x_axis,
        bins=bins,
        min_step=min_step,
        max_step=max_step,
        last=last,
        limit=limit,
        after=after,
        follow=follow,
        idle_timeout=idle_timeout,
    )


@leet.command(cls=ScriptCommand)
@click.argument("path", nargs=1, type=click.STRING, required=False)
@click.option(
    "--run",
    default="",
    metavar="RUN",
    help="The run to read: its directory name, its ID or its display name."
    " Defaults to the newest run.",
)
@click.option(
    "--keys",
    default="",
    metavar="KEYS",
    help="Comma-separated summary and history keys or globs with * and ? to report,"
    " e.g. 'val/*,train/loss'. A glob never matches keys starting with _.",
)
@click.help_option("-h", "--help")
def summary(path: str | None = None, run: str = "", keys: str = "") -> None:
    """Print a run's state, latest metrics, config and console tail as JSON.

    Prints one JSON object with the run's identity, state, exit code and
    last step, its summary and config, the keys it logged to its history
    with each one's count, last value and last step, and its last 50
    console lines.

    \b
    Examples:
        wandb leet summary
        wandb leet summary --keys 'val/*,train/loss'
        wandb leet summary ./wandb --run sim-unstable-L32
        wandb leet summary https://wandb.ai/<entity>/<project>/runs/<run-id>

    PATH can be a .wandb file, a run directory containing one, a wandb
    directory, or the URL of a W&B run to read it from the server. If PATH
    is not provided, the configured wandb directory is used.
    """  # noqa: D301 -- the \b escape is click's marker to not rewrap Examples.
    launch_query("summary", path, run=run, keys=keys)


@leet.command(cls=ScriptCommand)
@click.argument("path", nargs=1, type=click.STRING, required=False)
@click.option(
    "--run",
    default="",
    metavar="RUN",
    help="The run to read: its directory name, its ID or its display name."
    " Defaults to the newest run.",
)
@click.option(
    "--last",
    type=int,
    default=None,
    metavar="N",
    help="Return only the last N matching lines. Defaults to 200.",
)
@click.option(
    "--grep",
    default="",
    metavar="REGEX",
    help="Return only the lines matching this regular expression.",
)
@click.option(
    "--since",
    default="",
    metavar="T",
    help="Return only the lines logged at or after this RFC 3339 time, or within"
    " this duration (e.g. 10m) of the run's last write, or of now while it runs."
    " A line redrawn in place keeps the time it was first written.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    metavar="N",
    help="Lines per call when paging from the start or from --after. Defaults to 1000.",
)
@click.option(
    "--after",
    default="",
    metavar="CURSOR",
    help="The next_cursor of a previous call, to continue after the lines it returned.",
)
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    help="Keep printing new lines as the run writes them, one JSON object per poll.",
)
@click.option(
    "--idle-timeout",
    default="",
    metavar="DURATION",
    help="With --follow, stop once the run's file has gone this long without"
    " a write (e.g. 30s, 1h; 0 waits forever). Defaults to 10m.",
)
@click.help_option("-h", "--help")
def console(
    path: str | None = None,
    run: str = "",
    last: int | None = None,
    grep: str = "",
    since: str = "",
    limit: int | None = None,
    after: str = "",
    follow: bool = False,
    idle_timeout: str = "",
) -> None:
    """Print the console output of a run as JSON.

    Prints one JSON object with the run's state and its console lines,
    assembled as LEET shows them, with ANSI escapes stripped. --grep and
    --since select lines, --last keeps the last N of them, and --limit
    with --after pages through them from the start.

    \b
    Examples:
        wandb leet console --last 200
        wandb leet console --grep 'explosion|nan' --since 2026-06-24T06:50:00Z
        wandb leet console --since 10m
        wandb leet console --last 50 --follow
        wandb leet console https://wandb.ai/<entity>/<project>/runs/<run-id>

    PATH can be a .wandb file, a run directory containing one, a wandb
    directory, or the URL of a W&B run to read it from the server. If PATH
    is not provided, the configured wandb directory is used.
    """  # noqa: D301 -- the \b escape is click's marker to not rewrap Examples.
    launch_query(
        "console",
        path,
        run=run,
        last=last,
        grep=grep,
        since=since,
        limit=limit,
        after=after,
        follow=follow,
        idle_timeout=idle_timeout,
    )


@leet.command(cls=ScriptCommand)
@click.argument("path", nargs=1, type=click.STRING, required=False)
@click.option(
    "--run",
    default="",
    metavar="RUN",
    help="The run to read: its directory name, its ID or its display name."
    " Defaults to the newest run.",
)
@click.option(
    "--keys",
    default="",
    metavar="KEYS",
    help="Comma-separated system metric keys or globs with * and ?,"
    " e.g. 'system.gpu.*.gpu,system.memory*'. Defaults to every key.",
)
@click.option(
    "--since",
    default="",
    metavar="T",
    help="Return only the samples taken at or after this RFC 3339 time, or within"
    " this duration (e.g. 10m) of the run's last sample, or of now while it runs.",
)
@click.option(
    "--bins",
    type=int,
    default=None,
    metavar="N",
    help="Aggregate each metric into N equal-width bins over time instead of"
    " returning rows.",
)
@click.option(
    "--last",
    type=int,
    default=None,
    metavar="N",
    help="Return only the last N samples.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    metavar="N",
    help="Samples to return. Defaults to 1000.",
)
@click.help_option("-h", "--help")
def system(
    path: str | None = None,
    run: str = "",
    keys: str = "",
    since: str = "",
    bins: int | None = None,
    last: int | None = None,
    limit: int | None = None,
) -> None:
    """Print the system metrics of a run as JSON.

    Prints one JSON object with the run's state and the samples of its
    system metrics (CPU, memory, GPU, disk, network) on _timestamp, or
    with --bins their min, max, average and last value per bin with each
    metric's title and unit. Keys carry the system. prefix, as the W&B UI
    names them. Only local runs are read.

    \b
    Examples:
        wandb leet system --bins 60
        wandb leet system --keys 'system.gpu.*.gpu,system.memory*' --since 10m --bins 60
        wandb leet system --last 10
        wandb leet system ./wandb --run sim-unstable-L32 --keys 'system.gpu.*'

    PATH can be a .wandb file, a run directory containing one, or a
    wandb directory. If PATH is not provided, the configured wandb
    directory is used.
    """  # noqa: D301 -- the \b escape is click's marker to not rewrap Examples.
    launch_query(
        "system",
        path,
        run=run,
        keys=keys,
        since=since,
        bins=bins,
        last=last,
        limit=limit,
    )


@leet.command(cls=ScriptCommand)
@click.argument("args", nargs=-1, required=True, metavar="[PATH] METHOD")
@click.option(
    "--params",
    default="",
    metavar="JSON",
    help="The parameters of the request as a JSON object,"
    ' e.g. \'{"filter": "cfg.lr>=0.001"}\'.',
)
@click.help_option("-h", "--help")
def session(args: tuple[str, ...], params: str) -> None:
    """Steer the LEET a user has open on a wandb directory.

    Sends one request to the running LEET and prints its JSON reply.
    METHOD is one of status, runs.select, runs.deselect, runs.pin,
    runs.open, runs.close, filter.set, metrics.focus, step.goto, action
    and actions.

    \b
    Examples:
        wandb leet session status
        wandb leet session runs.select --params '{"filter": "cfg.lr>=0.001"}'
        wandb leet session filter.set --params '{"target": "metrics", "query": "loss"}'
        wandb leet session metrics.focus --params '{"key": "train/loss"}'
        wandb leet session step.goto --params '{"step": 4200}'
        wandb leet session action --params '{"name": "workspace.next_page", "key": "n"}'
        wandb leet session actions

    PATH is the wandb directory LEET shows. If PATH is not provided, the
    configured wandb directory is used.
    """  # noqa: D301 -- the \b escape is click's marker to not rewrap Examples.
    if len(args) > 2:
        _fatal_json("bad_request", f"unexpected argument: {args[2]}")
    if len(args) == 1 and os.path.exists(args[0]):
        _fatal_json("bad_request", "METHOD required after PATH")
    path = args[0] if len(args) == 2 else None
    try:
        request_params: Any = json.loads(params) if params else {}
    except json.JSONDecodeError as e:
        _fatal_json("bad_request", f"--params is not JSON: {e}")
    if not isinstance(request_params, dict):
        _fatal_json("bad_request", "--params must be a JSON object")
    launch_session(
        path,
        {"jsonrpc": "2.0", "id": 1, "method": args[-1], "params": request_params},
    )


@leet.command()
def config() -> None:
    """Edit LEET configuration."""
    launch_config()


@click.command()
@click.help_option("-h", "--help")
def mcp() -> None:
    """Serve W&B runs to an MCP client over stdio.

    The tools are the `wandb leet` query commands with the same JSON, for
    local runs and for the runs of the configured W&B server when you are
    logged in.

    \b
    Example client configuration:
        {"mcpServers": {"wandb": {"command": "wandb", "args": ["mcp"]}}}
    """  # noqa: D301 -- the \b escape is click's marker to not rewrap the example.
    settings = wandb_setup.singleton().settings
    args = _base_args("mcp")
    if "--base-url" not in args:
        args.extend(["--base-url", settings.base_url])
    if app_urls := _app_urls(settings.base_url):
        args.extend(["--app-urls", ",".join(app_urls)])

    env = os.environ.copy()
    try:
        auth = wbauth.authenticate_session(
            host=settings.base_url,
            source="wandb mcp",
            prompt=False,
            update_session=False,
        )
    except AuthenticationError:
        auth = None
    if isinstance(auth, wbauth.AuthApiKey):
        env["WANDB_API_KEY"] = auth.api_key
    _run_core(args, env)


class LaunchConfig:
    """Configuration for launching LEET."""


@dataclasses.dataclass(frozen=True)
class LocalLaunchConfig(LaunchConfig):
    """Configuration for launching LEET."""

    wandb_dir: str
    run_file: str | None = None


@dataclasses.dataclass(frozen=True)
class RemoteLaunchConfig(LaunchConfig):
    """Configuration for launching LEET against a remote project or run.

    The URL is the single source of truth: it is parsed here for early
    validation and host canonicalization, and again by wandb-core to
    derive the entity, project, and optional run ID.
    """

    remote_url: str
    api_key: str


def _fatal(message: str) -> Never:
    """Print an error message and exit with code 1."""
    click.echo(f"Error: {message}", err=True)
    sys.exit(1)


def _fatal_json(code: str, message: str) -> Never:
    """Print an error as one line of JSON and exit with code 1."""
    error = {"schema": "leet.error/1", "error": code, "message": message}
    click.echo(
        json.dumps(error, separators=(",", ":"), sort_keys=True, ensure_ascii=False),
        err=True,
    )
    sys.exit(1)


def _find_wandb_file_in_dir(dir_path: pathlib.Path) -> pathlib.Path | None:
    """Find a run-*.wandb file in the given directory.

    Returns None if not found or multiple found.
    """
    wandb_files = list(dir_path.glob("run-*.wandb"))
    if len(wandb_files) == 1:
        return wandb_files[0]
    return None


def _resolve_path(path: str | None) -> LocalLaunchConfig:
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


def _base_args(*command: str) -> list[str]:
    """Build the arguments for a wandb-core command and its common flags."""
    try:
        core_path = get_core_path()
    except WandbCoreNotAvailableError as e:
        get_telemetry_recorder().exception(
            WandbCoreNotAvailableError(f"using `wandb {command[0]}`. failed with {e}"),
            attributes=e.context,
        )
        _fatal(str(e))

    args = [core_path, *command]

    settings = wandb_setup.singleton().settings
    if settings._offline or settings._noop or not error_reporting_enabled():
        args.append("--no-observability")
    else:
        # Tell wandb-core which W&B server to upload telemetry to.
        args.extend(["--base-url", settings.base_url])

    if is_debug(default="False"):
        args.extend(["--log-level", "-4"])

    return args


def _run_core(args: list[str], env: dict[str, str] | None = None) -> Never:
    """Run wandb-core with the given arguments and exit with its return code."""
    try:
        result = subprocess.run(args, env=env, close_fds=True)
        sys.exit(result.returncode)
    except Exception as e:
        get_telemetry_recorder().reraise(e)


def launch(path: str | None, pprof: str) -> Never:
    """Launch the LEET TUI."""
    if path is not None and (path.startswith("https://") or path.startswith("http://")):
        try:
            config = _create_remote_launch_config(path)
        except (ValueError, UsageError, AuthenticationError) as e:
            _fatal(str(e))
    else:
        config = _resolve_path(path)

    args = _base_args("leet", "run")
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


def launch_inspect(
    path: str | None,
    summary: bool = False,
    json_output: bool = False,
    follow: bool = False,
    idle_timeout: str = "",
) -> Never:
    """Launch the transaction log record inspector."""
    config = _resolve_path(path)
    if not isinstance(config, LocalLaunchConfig):
        _fatal("`wandb leet inspect` requires a local .wandb file.")

    args = _base_args("leet", "inspect")
    if summary:
        args.append("--summary")
    if json_output:
        args.append("--json")
    if follow:
        args.append("--follow")
    if idle_timeout:
        args.extend(["--idle-timeout", idle_timeout])
    args.extend(_get_local_launch_args(config))

    _run_core(args)


def launch_query(
    command: str, path: str | None, **flags: str | int | bool | None
) -> Never:
    """Run a wandb-core leet query command on a local run or a W&B URL.

    Each flag is passed to wandb-core under its own name with underscores
    replaced by dashes; flags that are unset, empty or False are left out.
    """
    env = None
    if path is not None and path.startswith(("https://", "http://")):
        if command in ("history", "system"):
            _fatal(f"`wandb leet {command}` requires a local .wandb file.")
        source_args, env = _remote_query_source(path, flags)
    else:
        source_args = _local_query_source(path)

    args = _base_args("leet", command)
    for name, value in flags.items():
        if value is None or value == "" or value is False:
            continue
        flag = "--" + name.replace("_", "-")
        if value is True:
            args.append(flag)
        else:
            args.extend([flag, str(value)])
    args.extend(source_args)

    _run_core(args, env)


def _remote_query_source(
    path: str, flags: dict[str, str | int | bool | None]
) -> tuple[list[str], dict[str, str]]:
    """The source arguments and environment of a query on a W&B URL."""
    if flags.get("run"):
        _fatal_json("bad_request", "run cannot be used with a URL")
    try:
        remote = _create_remote_launch_config(path)
    except ValueError as e:
        _fatal_json("bad_request", str(e))
    except (UsageError, AuthenticationError) as e:
        _fatal_json("not_available", str(e))
    env = os.environ | {"WANDB_API_KEY": remote.api_key}
    return _get_remote_launch_args(remote), env


def _local_query_source(path: str | None) -> list[str]:
    """The source arguments of a query on a local run."""
    if path and not os.path.exists(path):
        _fatal_json("path_not_found", f"path does not exist: {path}")
    if path and os.path.isfile(path) and not path.endswith(".wandb"):
        _fatal_json("bad_request", f"not a .wandb file: {path}")
    return _get_local_launch_args(_resolve_path(path))


def launch_session(path: str | None, request: dict[str, Any]) -> Never:
    """Send a JSON-RPC request to the LEET showing a wandb directory."""
    if path is not None and path.startswith(("https://", "http://")):
        _fatal_json(
            "bad_request",
            "session requires a local wandb directory:"
            " a run on the W&B server cannot be steered",
        )
    if path and not os.path.exists(path):
        _fatal_json("path_not_found", f"path does not exist: {path}")
    wandb_dir = _resolve_path(path).wandb_dir

    args = _base_args("leet", "session")
    args.extend(["--request", json.dumps(request), wandb_dir])
    _run_core(args)


def launch_config() -> Never:
    """Launch the LEET configuration editor."""
    _run_core(_base_args("leet", "config"))


def launch_symon(pprof: str = "", interval: str = "") -> Never:
    """Launch the standalone system monitor."""
    args = _base_args("leet", "symon")

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
    """Create a LEET launch configuration for a remote project or run.

    Raises ValueError for an invalid URL and UsageError or
    AuthenticationError when no API key is found for its server.
    """
    base_url, remote_url = _parse_remote_url(path)

    auth = wbauth.authenticate_session(
        host=base_url,
        source="wandb-cli",
        no_offline=True,
        input_timeout=wandb_setup.singleton().settings.login_timeout,
        update_session=False,
    )
    if not isinstance(auth, wbauth.AuthApiKey):
        raise UsageError("LEET remote runs require API key authentication.")

    return RemoteLaunchConfig(remote_url=remote_url, api_key=auth.api_key)


def _app_urls(base_url: str) -> list[str]:
    """The W&B app URL prefixes whose pages name the API server at base_url."""
    prefixes = []
    if base_url in (urls.DEFAULT_BASE_URL, "https://api.wandb.ai"):
        prefixes.append("https://wandb.ai")
    for host, api in urls.FORGE_HOSTS.items():
        if base_url == f"https://api.{host}":
            paths = (urls.FORGE_API_PATH, urls.FORGE_APP_PATH, "")
            prefixes.extend(f"https://{host}{p}" for p in paths)
            prefixes.append(f"https://{api}")
    return prefixes


def _parse_remote_url(path: str) -> tuple[str, str]:
    """Validate a W&B project or run URL and return (base_url, canonical_url).

    Canonicalization maps W&B app URLs to their API base URLs and keeps only
    the entity, the project and, for a run page, the run ID. Raises
    ValueError for any other URL.
    """
    invalid = ValueError(
        f"Invalid remote URL: {path!r}."
        " Expected format: https://<host>/<entity>/<project>"
        " or https://<host>/<entity>/<project>/runs/<run_id>"
    )
    parsed_url = urllib.parse.urlparse(path)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise invalid

    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    run_path = parsed_url.path
    if parsed_url.hostname == "wandb.ai":
        base_url = urls.DEFAULT_BASE_URL
    elif parsed_url.hostname in urls.FORGE_HOSTS:
        base_url = f"https://api.{parsed_url.hostname}"
        for prefix in (urls.FORGE_API_PATH, urls.FORGE_APP_PATH):
            if run_path.startswith(prefix + "/"):
                run_path = run_path.removeprefix(prefix)
                break

    parts = run_path.strip("/").split("/")
    if len(parts) < 2 or not all(parts[:2]):
        raise invalid

    remote_url = f"{base_url}/{parts[0]}/{parts[1]}"
    if len(parts) >= 4 and parts[2] == "runs" and parts[3]:
        remote_url += f"/runs/{parts[3]}"
    return base_url, remote_url
