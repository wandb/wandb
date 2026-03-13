"""Beta versions of wandb CLI commands.

These commands are experimental and may change or be removed in future versions.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import click

import wandb
from wandb.analytics import get_sentry
from wandb.cli.beta_run import (
    DEFAULT_RUN_IMAGE,
    EVAL_JOB,
    SandboxConfigError,
    _parse_secrets,
    script_sandbox_path,
    submit_sandbox_job,
)
from wandb.errors import WandbCoreNotAvailableError
from wandb.util import get_core_path

_EVAL_IMAGE = "exianwb/inspect_ai_evals:latest"


def _require_auth(ctx: click.Context) -> None:
    """Ensure the user is logged in, prompting login if needed.

    Uses ``ctx.invoke(login)`` for consistency with other CLI commands.
    """
    from wandb.cli.cli import _get_cling_api, login

    api = _get_cling_api()
    if not api.is_authenticated:
        wandb.termlog("Login to W&B to use this feature")
        ctx.invoke(login, no_offline=True)
        api = _get_cling_api(reset=True)
        if not api.is_authenticated:
            raise click.UsageError("Not logged in. Run `wandb login` to authenticate.")


class DefaultCommandGroup(click.Group):
    """A click Group that falls through to a default command.

    If the first argument isn't a recognized subcommand, the default
    command is invoked with all arguments passed through. This allows
    backward-compatible CLIs where `cmd [path]` and `cmd run [path]`
    are equivalent.
    """

    def __init__(self, *args: Any, default_cmd: str = "run", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.default_cmd = default_cmd

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if not args or args[0].startswith("-") or args[0] not in self.commands:
            args = [self.default_cmd, *args]
        return super().parse_args(ctx, args)

    def format_usage(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write_usage(ctx.command_path, "[PATH] | COMMAND [ARGS]...")


@click.group()
def beta() -> None:
    """Beta versions of wandb CLI commands.

    These commands may change or even completely break in any release of wandb.
    """
    get_sentry().configure_scope(process_context="wandb_beta")

    try:
        get_core_path()
    except WandbCoreNotAvailableError as e:
        get_sentry().exception(f"using `wandb beta`. failed with {e}")
        click.secho(
            (e),
            fg="red",
            err=True,
        )


@beta.group(cls=DefaultCommandGroup, default_cmd="run", invoke_without_command=True)
@click.pass_context
def leet(ctx: click.Context) -> None:
    """W&B LEET: the Lightweight Experiment Exploration Tool.

    A terminal UI for viewing your W&B runs locally.

    Examples:
        wandb beta leet                 View latest run
        wandb beta leet ./wandb         View runs in directory
    """
    pass


@leet.command()
@click.argument("path", nargs=1, type=click.Path(exists=True), required=False)
@click.option(
    "--pprof",
    default="",
    hidden=True,
    help="Serve /debug/pprof/* on this address (e.g. 127.0.0.1:6060).",
)
@click.help_option("-h", "--help")
def run(path: str | None = None, pprof: str = "") -> None:
    """Launch the LEET TUI.

    PATH can be a .wandb file, a run directory, or a wandb directory.
    If omitted, searches for the latest run.
    """
    from . import beta_leet

    beta_leet.launch(path, pprof)


@leet.command()
def config() -> None:
    """Edit LEET configuration."""
    from . import beta_leet

    beta_leet.launch_config()


@beta.command()
@click.argument("paths", type=click.Path(exists=True), nargs=-1)
@click.option(
    "--live",
    is_flag=True,
    default=False,
    help="""Sync a run while it's still being logged.

    This may hang if the process generating the run crashes uncleanly.
    """,
)
@click.option(
    "-e",
    "--entity",
    default="",
    help="An entity override to use for all runs being synced.",
)
@click.option(
    "-p",
    "--project",
    default="",
    help="A project override to use for all runs being synced.",
)
@click.option(
    "--id",
    "run_id",
    default="",
    help="""A run ID override to use for all runs being synced.

    If setting this and syncing multiple files (with the same entity
    and project), the files will be synced in order of start time.
    This is intended to work with syncing multiple resumed fragments
    of the same run.
    """,
)
@click.option(
    "--job-type",
    default="",
    help="A job type override for all runs being synced.",
)
@click.option(
    "--replace-tags",
    default="",
    help="Rename tags using the format 'old1=new1,old2=new2'.",
)
@click.option(
    "--skip-synced/--no-skip-synced",
    is_flag=True,
    default=True,
    help="Skip runs that have already been synced with this command.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would happen without uploading anything.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Print more information.",
)
@click.option(
    "-n",
    default=5,
    help="""Max number of runs to sync at a time.

    When syncing multiple files that are part of the same run,
    the files are synced sequentially in order of start time
    regardless of this setting. This happens for resumed runs
    or when using the --id parameter.
    """,
)
def sync(
    paths: tuple[str, ...],
    live: bool,
    entity: str,
    project: str,
    run_id: str,
    job_type: str,
    replace_tags: str,
    skip_synced: bool,
    dry_run: bool,
    verbose: bool,
    n: int,
) -> None:
    """Upload .wandb files specified by PATHS.

    This is a beta re-implementation of `wandb sync`.
    It is not feature complete, not guaranteed to work, and may change
    in backward-incompatible ways in any release of wandb.

    PATHS can include .wandb files, run directories containing .wandb files,
    and "wandb" directories containing run directories.

    For example, to sync all runs in a directory:

        wandb beta sync ./wandb

    To sync a specific run:

        wandb beta sync ./wandb/run-20250813_124246-n67z9ude

    Or equivalently:

        wandb beta sync ./wandb/run-20250813_124246-n67z9ude/run-n67z9ude.wandb
    """
    from . import beta_sync

    beta_sync.sync(
        [pathlib.Path(path) for path in paths],
        live=live,
        entity=entity,
        project=project,
        run_id=run_id,
        job_type=job_type,
        replace_tags=replace_tags,
        dry_run=dry_run,
        skip_synced=skip_synced,
        verbose=verbose,
        parallelism=n,
    )


@beta.command(
    context_settings={"ignore_unknown_options": True},
)
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
@click.option("-q", "--queue", required=True, help="Launch queue name.")
@click.option("--project", default=None, help="W&B project.")
@click.option("--entity", default=None, help="W&B entity.")
@click.option(
    "--entity-name", required=True, help="W&B entity display name (WANDB_ENTITY_NAME)."
)
@click.option("-i", "--image", default=None, help="Container image.")
@click.option(
    "-e", "--env", multiple=True, help="Environment variable (KEY=VAL). Repeatable."
)
@click.option("--resources", default=None, help="Resource requests as JSON.")
@click.option(
    "-t", "--timeout", type=int, default=None, help="Max lifetime in seconds."
)
@click.option(
    "-m",
    "--mount",
    multiple=True,
    help=(
        "File to mount into sandbox (LOCAL[:SANDBOX_PATH]). Repeatable. "
        "SANDBOX_PATH must be an absolute path."
    ),
)
@click.option("--tag", "tags", multiple=True, help="Tag. Repeatable.")
@click.option(
    "--tower-id", "tower_ids", multiple=True, help="Aviato tower ID. Repeatable."
)
@click.option(
    "-s",
    "--secret",
    "secrets",
    multiple=True,
    help=(
        "Secret to inject ([DESTINATION_ENV_VAR:]SECRET_KEY_NAME). Repeatable. "
        "If DESTINATION_ENV_VAR is omitted, SECRET_KEY_NAME is used."
    ),
)
@click.option(
    "--dry-run", is_flag=True, default=False, help="Print config without submitting."
)
@click.pass_context
def run(
    ctx: click.Context,
    command: tuple[str, ...],
    queue: str,
    project: str | None,
    entity: str | None,
    entity_name: str,
    image: str | None,
    env: tuple[str, ...],
    resources: str | None,
    timeout: int | None,
    mount: tuple[str, ...],
    tags: tuple[str, ...],
    tower_ids: tuple[str, ...],
    secrets: tuple[str, ...],
    dry_run: bool,
) -> None:
    """Run a script in a remote sandbox.

    Example: wandb beta run train.py -q my-queue -i pytorch:latest
    """
    if not dry_run:
        _require_auth(ctx)

    if not command:
        raise click.UsageError(
            "Missing script path. Usage: wandb beta run SCRIPT [ARGS...]"
        )

    script = command[0]
    sandbox_path = script_sandbox_path(script)
    script_args = list(command[1:])

    try:
        result = submit_sandbox_job(
            command="python",
            args=[sandbox_path, *script_args],
            image=image or DEFAULT_RUN_IMAGE,
            env=list(env) or None,
            secrets=_parse_secrets(list(secrets)) or None,
            resources=resources,
            timeout=timeout,
            script=script,
            mounts=list(mount) or None,
            tags=list(tags) or None,
            tower_ids=list(tower_ids) or None,
            project=project,
            entity=entity,
            entity_name=entity_name,
            queue=queue,
            dry_run=dry_run,
        )
    except SandboxConfigError as e:
        raise click.UsageError(str(e)) from e

    if dry_run:
        click.echo(json.dumps(result, indent=2))
    elif result is not None:
        click.echo(f"Queued run: {result}")


@beta.command(
    name="eval",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("tasks", nargs=-1, required=True)
@click.option(
    "-m", "--model", required=True, help="Model to evaluate (e.g. openai/gpt-4)."
)
@click.option("--model-base-url", default=None, help="Model API base URL.")
@click.option("--limit", type=int, default=None, help="Max samples per task.")
@click.option(
    "--create-leaderboard",
    is_flag=True,
    default=False,
    help="Publish results to a Weave leaderboard.",
)
@click.option("-q", "--queue", required=True, help="Launch queue name.")
@click.option("--project", default=None, help="W&B project.")
@click.option("--entity", default=None, help="W&B entity.")
@click.option(
    "--entity-name", required=True, help="W&B entity display name (WANDB_ENTITY_NAME)."
)
@click.option(
    "-e", "--env", multiple=True, help="Environment variable (KEY=VAL). Repeatable."
)
@click.option("--resources", default=None, help="Resource requests as JSON.")
@click.option(
    "-t", "--timeout", type=int, default=None, help="Max lifetime in seconds."
)
@click.option(
    "--tower-id", "tower_ids", multiple=True, help="Aviato tower ID. Repeatable."
)
@click.option(
    "--model-secret",
    "model_secret_name",
    default=None,
    metavar="SECRET_NAME",
    help=(
        "Name of the team secret that holds the model API key "
        "(e.g. OPENAI_API_KEY). Manage secrets in your team settings."
    ),
)
@click.option(
    "--hf-secret",
    "hf_secret_name",
    default=None,
    metavar="SECRET_NAME",
    help=(
        "Name of the team secret that holds a HuggingFace access token "
        "(e.g. HF_TOKEN). Manage secrets in your team settings."
    ),
)
@click.option(
    "--scorer-secret",
    "scorer_secret_name",
    default=None,
    metavar="SECRET_NAME",
    help=(
        "Name of the team secret that holds the scorer model API key "
        "(e.g. OPENAI_API_KEY). Manage secrets in your team settings."
    ),
)
@click.option(
    "--dry-run", is_flag=True, default=False, help="Print config without submitting."
)
@click.pass_context
def eval_cmd(
    ctx: click.Context,
    tasks: tuple[str, ...],
    model: str,
    model_base_url: str | None,
    limit: int | None,
    create_leaderboard: bool,
    queue: str,
    project: str | None,
    entity: str | None,
    entity_name: str,
    env: tuple[str, ...],
    resources: str | None,
    timeout: int | None,
    tower_ids: tuple[str, ...],
    model_secret_name: str | None,
    hf_secret_name: str | None,
    scorer_secret_name: str | None,
    dry_run: bool,
) -> None:
    r"""Thin wrapper around ``inspect eval`` that runs in an Aviato sandbox.

    \b
    Example:
        wandb beta eval swebench -m openai/gpt-4 -q my-queue
        wandb beta eval swebench mmlu_pro -m openai/gpt-4 -q q --limit 10
    """
    if not dry_run:
        _require_auth(ctx)

    eval_args: list[str] = ["evals.py", *tasks, "--model", model]
    if model_base_url:
        eval_args.extend(["--model-base-url", model_base_url])
    if limit is not None:
        eval_args.extend(["--limit", str(limit)])
    if create_leaderboard:
        eval_args.append("--create-leaderboard")
    eval_args.extend(ctx.args or [])

    secrets = {}
    if model_secret_name:
        secrets["model_api_key"] = model_secret_name
    if hf_secret_name:
        secrets["hf_token"] = hf_secret_name
    if scorer_secret_name:
        secrets["scorer_api_key"] = scorer_secret_name

    try:
        result = submit_sandbox_job(
            job=EVAL_JOB,
            command="python3",
            args=eval_args,
            image=_EVAL_IMAGE,
            env=list(env) or None,
            secrets=secrets or None,
            resources=resources,
            timeout=timeout,
            tower_ids=list(tower_ids) or None,
            project=project,
            entity=entity,
            entity_name=entity_name,
            queue=queue,
            dry_run=dry_run,
        )
    except SandboxConfigError as e:
        raise click.UsageError(str(e)) from e

    if dry_run:
        click.echo(json.dumps(result, indent=2))
    elif result is not None:
        click.echo(f"Queued eval run: {result}")
