from __future__ import annotations

import os
from enum import Enum
from operator import attrgetter
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from rich.console import Console
from typer import Argument, Option, Typer
from typer.main import get_command as typer_get_command

from wandb import Api
from wandb.cli.cli import artifact

from .diffs import ArtifactTreeDiff, DataDiff, TableComparator
from .interactive_diff import run_interactive_diff
from .select_artifact import run_selector

if TYPE_CHECKING:
    from wandb import Artifact

os.environ["WANDB_SHOW_INFO"] = "false"

app = Typer(
    add_help_option=True,
    pretty_exceptions_show_locals=True,
    pretty_exceptions_enable=True,
)

console = Console()
err_console = Console(stderr=True)


class DisplayMode(Enum):
    UNIFIED = "unified"
    SIDE_BY_SIDE = "side-by-side"


@app.command()
def diff(
    artifact1: Annotated[
        str | None,
        Argument(
            help="First artifact path (e.g., 'project/artifact:v1'). If omitted, you'll be prompted to pick one.",
        ),
    ] = None,
    artifact2: Annotated[
        str | None,
        Argument(
            help="Second artifact path. If omitted, compares with previous version.",
        ),
    ] = None,
    mode: Annotated[
        DisplayMode,
        Option(
            "-m",
            help="Display mode.",
        ),
    ] = DisplayMode.SIDE_BY_SIDE,
    diff_data: Annotated[
        bool,
        Option(
            "--data/--no-data",
            help="Show data comparison (not just file structure)",
        ),
    ] = True,
    sample_size: Annotated[
        int | None,
        Option(
            "--sample",
            "-s",
            help="Number of rows to sample for data comparison",
        ),
    ] = 1_000,
    interactive: Annotated[
        bool,
        Option(
            "--interactive/--no-interactive",
            "-i/-I",
            help="Launch interactive TUI for exploring diffs",
        ),
    ] = True,
    debug: Annotated[
        bool,
        Option(
            "-D",
            help="Enable debug mode",
        ),
    ] = True,
) -> None:
    """Compare two artifact versions side-by-side."""
    import click

    api = Api()

    # ------------------------------------------------------------------
    # Interactive prompts if artifact1 is missing
    # ------------------------------------------------------------------
    if artifact1 is None:
        if (path := run_selector(api)) is None:
            raise click.Abort()
        artifact1 = path

    if interactive:
        # Launch interactive diff app
        return run_interactive_diff(artifact1, artifact2, diff_data, sample_size)

    # Fetch artifacts
    art1 = api.artifact(artifact1)

    if artifact2:
        art2 = api.artifact(artifact2)
    else:
        # Infer previous version automatically
        last_artifact = infer_prev_artifact(art1)

        if last_artifact:
            art2 = last_artifact
        else:
            console.print("[red]No previous version found[/red]")
            return

    # Display file tree comparison
    tree_diff = ArtifactTreeDiff(art1, art2)
    tree_diff.display_side_by_side()

    # Download and compare data if requested
    if diff_data:
        console.print("\n[bold]Data Comparison[/bold]\n")

        # Download artifacts
        root1 = Path(art1.download(multipart=True))
        root2 = Path(art2.download(multipart=True))

        # Get comparator
        common_comparator = TableComparator()

        # Compare data from shared files
        relpaths1 = set(
            p.relative_to(root1) for p in filter(Path.is_file, root1.rglob("*"))
        )
        relpaths2 = set(
            p.relative_to(root2) for p in filter(Path.is_file, root2.rglob("*"))
        )
        shared_relpaths = sorted(relpaths1 & relpaths2)

        common_paths1 = sorted(map(root1.joinpath, shared_relpaths))
        common_paths2 = sorted(map(root2.joinpath, shared_relpaths))

        shared_files_block = "\n".join(f" - {pth!s}" for pth in shared_relpaths)
        console.print("Comparing common files:", style="bold cyan")
        console.print(shared_files_block, style="bold cyan")

        # console.print(f"\n[bold cyan]Comparing \n{shared_files_block}[/bold cyan]")
        common_result = common_comparator.compare(
            common_paths1, common_paths2, sample_size
        )
        _ = DataDiff(common_result).display_summary_table().display_schema_changes()

        # ------------------------------------------------------------------------------
        all_paths1 = sorted(map(root1.joinpath, relpaths1))
        all_paths2 = sorted(map(root2.joinpath, relpaths2))
        console.print("Comparing all files:", style="bold cyan")
        all_result = common_comparator.compare(all_paths1, all_paths2, sample_size)
        _ = DataDiff(all_result).display_summary_table().display_schema_changes()


def infer_prev_artifact(art1: Artifact):
    prev_artifacts = (
        a for a in art1.source_collection.artifacts() if a.version < art1.version
    )
    last_artifact = max(prev_artifacts, key=attrgetter("version"), default=None)
    return last_artifact


typer_click_object = typer_get_command(app)

artifact.add_command(typer_click_object, "diff")
