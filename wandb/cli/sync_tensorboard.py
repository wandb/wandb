"""Implements `wandb sync-tensorboard`."""

import click

import wandb


@click.command()
@click.argument("path")
@click.option(
    "--save-to",
    help="""Run folder where to put the tfevents files.

    Defaults to the run's root directory. Ignored if PATH is a cloud URI.
    """,
    default="",
)
@click.option(
    "--namespace",
    help="""Prefix to add to metric names. No prefix by default.""",
    default="",
)
def sync_tensorboard(
    path: str,
    save_to: str,
    namespace: str,
) -> None:
    """Sync TensorBoard tfevents files to W&B.

    This is a convenience command for using `wandb.init()` and calling
    `run.sync_tensorboard(..., existing_files=True)`.
    See the `run.sync_tensorboard()` method for more information about this
    feature and its options.
    """
    with wandb.init() as run:
        run.sync_tensorboard(
            path,
            save_to=save_to,
            namespace=namespace,
            existing_files=True,
        )
