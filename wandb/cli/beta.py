"""Beta versions of wandb CLI commands.

These commands are experimental and may change or be removed in future versions.
"""

from __future__ import annotations

import pathlib

import click

from wandb.analytics import get_sentry
from wandb.errors import WandbCoreNotAvailableError
from wandb.util import get_core_path

from .leet import leet


@click.group()
@click.pass_context
def beta(ctx: click.Context) -> None:
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

    if ctx.invoked_subcommand == "leet":
        click.secho(
            "LEET is now generally available as `wandb leet`;"
            " `wandb beta leet` is kept as an alias.",
            fg="yellow",
            err=True,
        )


# LEET graduated from beta; `wandb beta leet` is kept as an alias for
# `wandb leet` to avoid breaking existing users.
beta.add_command(leet)


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
    "--skip-online/--no-skip-online",
    is_flag=True,
    default=True,
    help="Skip online runs.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would happen without uploading anything.",
)
@click.option(
    "--yes",
    "skip_confirmation",
    is_flag=True,
    default=False,
    help="Skip confirmation.",
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
    skip_online: bool,
    dry_run: bool,
    skip_confirmation: bool,
    verbose: bool,
    n: int,
) -> None:
    """Upload .wandb files specified by PATHS.

    This is an improvement on `wandb sync` with additional features and better
    UX and performance. It will eventually be absorbed into `wandb sync`.

    PATHS can include .wandb files, run directories containing .wandb files,
    and "wandb" directories containing run directories.

    For example, to sync all runs in the current .wandb directory:

        $ wandb beta sync ./wandb

    To sync a specific run by specifying the run directory:

        $ wandb beta sync ./wandb/run-20250813_124246-n67z9ude

    Or equivalently:

        $ wandb beta sync ./wandb/run-20250813_124246-n67z9ude/run-n67z9ude.wandb
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
        skip_confirmation=skip_confirmation,
        skip_synced=skip_synced,
        skip_online=skip_online,
        verbose=verbose,
        parallelism=n,
    )


@beta.group()
def core() -> None:
    """Manage a shared local wandb-core service for multi-process workloads.

    wandb-core is the local backend process that handles run data,
    file uploads, and system metrics collection. By default, each
    process that calls `wandb.init()` starts its own backend. On a
    machine running many independent workers, that duplicates work
    and wastes CPU and memory.

    Use these commands to start one detached wandb-core instance and
    point multiple workers on the same machine at it with the
    WANDB_SERVICE environment variable.

    Typical workflow:

        $ wandb beta core start
        $ export WANDB_SERVICE=printed_value
        $ python -m your_launcher
        $ wandb beta core stop

    For shell scripts, capture the raw WANDB_SERVICE value from stdout:

        $ export WANDB_SERVICE="$(wandb beta core start)"

    The shared service exits after 10 minutes of idleness by default.
    Override this with --idle-timeout on the start command.
    """


try:
    from .beta_sandbox import sandbox as sandbox_group
except ImportError:
    pass
else:
    beta.add_command(sandbox_group)


@core.command()
@click.option(
    "--idle-timeout",
    default="10m",
    show_default=True,
    metavar="DURATION",
    help=(
        "Shut down wandb-core after this much idle time with no connected "
        "clients. Uses Go duration syntax, for example 30s, 10m, or 0 to "
        "disable idle shutdown."
    ),
)
def start(idle_timeout: str) -> None:
    """Start a detached wandb-core service."""
    from . import beta_core

    beta_core.start(idle_timeout=idle_timeout)


@core.command()
def stop() -> None:
    """Stop a detached wandb-core service.

    The service address is taken from the WANDB_SERVICE environment variable.
    """
    from . import beta_core

    beta_core.stop()
