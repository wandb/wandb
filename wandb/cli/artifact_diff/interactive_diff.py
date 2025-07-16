from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import suppress
from datetime import datetime
from enum import Enum, StrEnum, auto
from pathlib import Path
from typing import Any, assert_never

import numpy as np
import polars as pl
from humanize import naturalsize
from more_itertools import mark_ends
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import (
    Container,
    Horizontal,
    ScrollableContainer,
    Vertical,
    VerticalScroll,
)
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    ProgressBar,
    Rule,
    Select,
    Sparkline,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)

# -----------------------------------------------------------------------------
# Utilities / constants
# -----------------------------------------------------------------------------
from wandb import Api, Artifact
from wandb.cli.artifact_diff.utils import (
    BOLD,
    BOLD_BLUE,
    CYAN,
    DIM,
    GREEN,
    RED,
    format_cell,
    style_diff_frac,
)

from .diffs import (
    ArtifactTreeDiff,
    ColStats,
    ComparisonResult,
    NumericColStats,
    SBSResult,
    StringColStats,
    TableComparator,
)

# -----------------------------------------------------------------------------
# Version selector widget (defined early so type checker finds it)
# -----------------------------------------------------------------------------


class _Side(StrEnum):
    LEFT = auto()
    RIGHT = auto()


class VersionSelector(Static):
    """Dropdown to choose a version within the same artifact collection."""

    @dataclass
    class VersionChosen(Message):
        """Posted when a version is selected."""

        side: _Side
        version: str

        # def __init__(self, side: WhichSide, version: str) -> None:
        #     self.side = side  # "left" | "right"
        #     self.version = version
        #     super().__init__()

    def __init__(self, artifact: Artifact, side: str | _Side) -> None:
        super().__init__()
        self.artifact = artifact
        self.side = _Side(side)
        self._initial_handled = False  # to ignore the first auto-fired event

    def compose(self) -> ComposeResult:  # type: ignore[override]
        # Build options from collection versions (newest first)
        collection = self.artifact.collection
        versions = sorted(
            collection.artifacts(),
            key=lambda a: int(str(a.version).lstrip("v")),
            reverse=True,
        )
        opts = [(a.version, a.version) for a in versions]
        select = Select(
            options=opts, value=self.artifact.version, id=f"sel-{self.side.value}"
        )
        yield select

    @on(Select.Changed)
    def _changed(self, event: Select.Changed) -> None:  # type: ignore
        # Skip the automatic event fired immediately after mount
        if not self._initial_handled:
            self._initial_handled = True
            return

        self.post_message(self.VersionChosen(self.side, event.value))


# -----------------------------------------------------------------------------
# File tree filtering utilities
# -----------------------------------------------------------------------------


class FileFilterMode(Enum):
    ALL = "all"
    CHANGES = "changes"  # added / removed / modified
    UNCHANGED = "unchanged"

    def next(self) -> FileFilterMode:
        order = [FileFilterMode.ALL, FileFilterMode.CHANGES, FileFilterMode.UNCHANGED]
        idx = order.index(self)
        return order[(idx + 1) % len(order)]


def _get_previous_version(artifact: Artifact) -> Artifact | None:
    """Get the previous version of an artifact in its collection."""
    return max(
        filter(lambda a: a.version < artifact.version, artifact.collection.artifacts()),
        key=lambda a: int(a.version.removeprefix("v")),
    )


class DiffMode(Enum):
    UNIFIED = "unified"
    SIDE_BY_SIDE = "side-by-side"
    INLINE = "inline"


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class DiffData:
    """Container for Artifact diff data."""

    left: Artifact
    right: Artifact

    tree_diff: ArtifactTreeDiff

    comparison_result: ComparisonResult | None = None

    left_root: Path | None = None
    right_root: Path | None = None


class FilterableDataTable(DataTable):
    """DataTable with built-in filtering support."""

    filter_text = reactive("")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.original_data: tuple[tuple[Any, ...], ...] = []

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True

    def watch_filter_text(self, filter_text: str) -> None:
        """React to filter text changes."""
        if not self.original_data:
            return

        self.clear()
        match filter_text.split(":", maxsplit=1):
            case [value]:
                filtered_data = (
                    row
                    for row in self.original_data
                    if any(value.lower() in str(cell).lower() for cell in row)
                )
            case [col_name, value]:
                filtered_data = (
                    row
                    for row in self.original_data
                    if value.lower()
                    in str(row[self.get_column_index(col_name)]).lower()
                )
            case _:
                # TODO: Handle this more gracefully/visibly
                assert_never(filter_text)

        for row in filtered_data:
            self.add_row(*row)


class FileTreeDiffView(Container):
    """Interactive file tree view for artifact comparison."""

    ID_LEFT = "tree1"
    ID_RIGHT = "tree2"

    def __init__(self, diff_data: DiffData) -> None:
        super().__init__()
        self.diff_data = diff_data

        # self.tree1_data = {}  # Store file info for tree nodes
        # self.tree2_data = {}

        self.filter_mode: FileFilterMode = FileFilterMode.ALL

    def compose(self) -> ComposeResult:
        with Horizontal(classes="file-trees"):
            with VerticalScroll(classes="tree-container"):
                left_art = self.diff_data.left

                yield VersionSelector(left_art, side=_Side.LEFT)
                yield Label(Text(left_art.qualified_name, style=BOLD_BLUE))
                yield Tree("", id=self.ID_LEFT, classes="file-tree")

            yield Rule(orientation="vertical")

            with VerticalScroll(classes="tree-container"):
                right_art = self.diff_data.right

                yield VersionSelector(right_art, side=_Side.RIGHT)
                yield Label(Text(right_art.qualified_name, style=BOLD_BLUE))
                yield Tree("", id=self.ID_RIGHT, classes="file-tree")

    def on_mount(self) -> None:
        self._build_trees()

    def _build_trees(self) -> None:
        """Build interactive file trees."""
        tree_left = self.query_one(f"#{self.ID_LEFT}", Tree)
        tree_right = self.query_one(f"#{self.ID_RIGHT}", Tree)

        # Clear existing trees
        tree_left.clear()
        tree_right.clear()

        # Get all paths
        paths_left = set(self.diff_data.left.manifest.entries)
        paths_right = set(self.diff_data.right.manifest.entries)
        all_paths = sorted(paths_left | paths_right)

        # Build tree structure respecting filter mode
        for path in all_paths:
            status = self._determine_status(path, paths_left, paths_right)

            if self.filter_mode is FileFilterMode.CHANGES and status == "unchanged":
                continue
            if self.filter_mode is FileFilterMode.UNCHANGED and status != "unchanged":
                continue

            self._add_path_to_trees(
                path, paths_left, paths_right, tree_left, tree_right, status=status
            )

        # Auto-expand the tree for now
        tree_left.root.expand_all()
        tree_right.root.expand_all()

        # # Ensure the (invisible) root is expanded so its children are shown
        # tree1.root.expand()
        # tree2.root.expand()
        # # Also expand the first-level nodes for better visibility
        # for top_node in tree1.root.children:
        #     top_node.expand()
        # for top_node in tree2.root.children:
        #     top_node.expand()

    def _determine_status(
        self, path: str, paths_left: set[str], paths_right: set[str]
    ) -> str:
        """Return status string for a given path."""
        # TODO: use this if safe
        # paths_left = set(self.diff_data.left.manifest.entries)
        # paths_right = set(self.diff_data.right.manifest.entries)

        # in_left = path in paths_left
        # in_right = path in paths_right

        entry1 = self.diff_data.left.manifest.entries.get(path)
        entry2 = self.diff_data.right.manifest.entries.get(path)

        # if in_left and in_right:
        if entry1 and entry2:
            # entry1 = self.diff_data.left.manifest.entries[path]
            # entry2 = self.diff_data.right.manifest.entries[path]
            return "modified" if (entry1.digest != entry2.digest) else "unchanged"

        if entry1 and (not entry2):
            return "removed"

        if (not entry1) and entry2:
            return "added"

        assert_never(entry1, entry2)

    def _add_path_to_trees(
        self,
        path: str,
        paths_left: set[str],
        paths_right: set[str],
        tree_left: Tree,
        tree_right: Tree,
        status: str | None = None,
    ) -> None:
        """Add a path to both trees with appropriate styling."""
        parts = Path(path).parts
        # parts = path.split("/")

        in_left = path in paths_left
        in_right = path in paths_right

        # status may be pre-computed
        if status is None:
            status = self._determine_status(path, paths_left, paths_right)

        # Add to trees
        self._add_to_tree(tree_left, parts, path, status, is_left=True, exists=in_left)
        self._add_to_tree(
            tree_right, parts, path, status, is_left=False, exists=in_right
        )

    def _add_to_tree(
        self,
        tree: Tree,
        parts: list[str],
        full_path: str,
        status: str,
        is_left: bool,
        exists: bool,
    ) -> None:
        """Add a path to a single tree."""
        current = tree.root

        for _, is_file, part in mark_ends(parts):
            # Find or create node
            for child in current.children:
                if child.label.plain.rstrip("/") == part.rstrip("/"):
                    current = child
                    break

            # if not found:
            else:
                style_map = {
                    "added": ("green" if exists else "dim"),
                    "removed": ("red dim" if exists else "dim"),
                    "modified": "yellow",
                    "unchanged": "",
                }
                style = style_map.get(status, "")

                if is_file:
                    # ----- Leaf (file) ---------------------------------------------------
                    if exists:
                        # Get file size
                        if (
                            is_left
                            and full_path in self.diff_data.left.manifest.entries
                        ):
                            size = self.diff_data.left.manifest.entries[full_path].size
                        elif (
                            not is_left
                            and full_path in self.diff_data.right.manifest.entries
                        ):
                            size = self.diff_data.right.manifest.entries[full_path].size
                        else:
                            size = 0

                        size_str = self._format_size(size)
                        base_label = f"{part} {size_str}"
                        label = Text(base_label, style=style)
                    else:
                        placeholder = f"{part} =>" if is_left else f"=> {part}"
                        label = Text(placeholder, style=DIM)

                    # Use add_leaf so Textual doesn't show expand arrow
                    current = current.add_leaf(label)
                else:
                    # ----- Directory ------------------------------------------------------
                    base_label = f"{part}/"
                    label = Text(base_label, style=style)
                    current = current.add(label)

    def _format_size(self, size: int) -> str:
        """Format file size in human-readable format."""
        return naturalsize(size)


class DataComparisonView(Container):
    """View for comparing data between artifacts."""

    def __init__(self, diff_data: DiffData) -> None:
        super().__init__()
        self.diff_data = diff_data

    def compose(self) -> ComposeResult:
        # Make entire area scrollable so summary / stats aren't clipped
        with VerticalScroll(id="data-scroll"):
            yield Label(
                Text("Data Comparison", style=BOLD),
                classes="section-title",
            )

            if self.diff_data.comparison_result:
                # Summary stats
                with Container(classes="summary-stats"):
                    yield self._create_summary_table()

                # # Schema changes
                with Container(classes="schema-changes"):
                    yield from self._create_schema_changes()

                # Data preview with filtering
                with Container(classes="data-preview"):
                    yield Label(Text("Data Preview", style=BOLD))
                    yield Input(
                        placeholder="Filter rows...",
                        id="data-filter",
                        # compact=True,
                    )

                    with Horizontal():
                        with VerticalScroll(classes="data-table-container"):
                            yield Label(Text(self.diff_data.left.version, style=BOLD))
                            yield Rule()
                            yield FilterableDataTable(id="data1")

                        with VerticalScroll(classes="data-table-container"):
                            yield Label(Text(self.diff_data.right.version, style=BOLD))
                            yield Rule()
                            yield FilterableDataTable(id="data2")

                # Append detailed statistics summary below tables
                yield StatisticsView(self.diff_data)
            else:
                yield Label(Text("No data comparison available", style=DIM))

    def _create_summary_table(self) -> Static:
        """Create summary statistics table."""
        result = self.diff_data.comparison_result
        table = Table(title="Summary Statistics", box=None)

        table.add_column("Metric", style=CYAN)
        table.add_column(self.diff_data.left.version, justify="right", style=DIM)
        table.add_column(self.diff_data.right.version, justify="left", style=DIM)
        table.add_column("Change")

        # Row counts
        if row_info := result.summary.rows:
            change_str = f"{row_info.diff:+,d}"
            if (pct_change := row_info.pct_change) is not None:
                change_str += f" ({pct_change:+,.1f}%)"

            table.add_row(
                "Total Rows",
                f"{row_info.left:,d}",
                f"{row_info.right:,d}",
                Text(
                    change_str,
                    style=BOLD
                    if (pct_change is None)
                    else style_diff_frac(pct_change / 100),
                ),
            )

        # Column counts
        if schema := result.summary.schema:
            table.add_row(
                "Total Columns",
                f"{schema.total_columns.left:,d}",
                f"{schema.total_columns.right:,d}",
                f"{len(schema.added_columns):,d} added, {len(schema.removed_columns):,d} removed",
            )

        return Static(table)

    def _create_schema_changes(self) -> Iterator[Label]:
        """Create schema changes display."""
        schema = self.diff_data.comparison_result.summary.schema

        if not schema:
            return

        changes = []

        if schema.added_columns:
            changes += [
                Text("+ Added Columns:", style=Style.chain(BOLD, GREEN)),
                *(Text(f"  + {col!s}", style=GREEN) for col in schema.added_columns),
            ]

        if schema.removed_columns:
            changes += [
                Text("- Removed Columns:", style=Style.chain(BOLD, RED)),
                *(Text(f"  - {col!s}", style=RED) for col in schema.removed),
            ]

        if schema.type_changes:
            changes.append(Text("~ Type Changes:", style="yellow bold"))
            for col, change in schema.type_changes.items():
                changes.append(
                    Text(f"  ~ {col}: {change.left} → {change.right}", style="yellow")
                )

        if changes:
            for change in changes:
                yield Label(change)
        else:
            yield Label(Text("No schema changes", style=DIM))

    @on(Input.Changed, "#data-filter")
    def filter_data(self, event: Input.Changed) -> None:
        """Filter data tables based on input."""
        filter_text = event.value

        data1 = self.query_one("#data1", FilterableDataTable)
        data2 = self.query_one("#data2", FilterableDataTable)

        data1.filter_text = filter_text
        data2.filter_text = filter_text


# NOTE: reused but label text adjusted to "Summary"
class StatisticsView(ScrollableContainer):
    """View for detailed statistics and visualizations."""

    def __init__(self, diff_data: DiffData) -> None:
        super().__init__()
        self.diff_data = diff_data

    def compose(self) -> ComposeResult:
        yield Label(
            Text("Summary", style=BOLD),
            classes="section-title",
        )

        if (cmp_result := self.diff_data.comparison_result) and (
            stats := cmp_result.details.column_stats
        ):
            with VerticalScroll(classes="stats-scroll"):
                for col_name, col_stats in stats.items():
                    with Vertical():
                        with Container(classes="column-stats"):
                            yield Label(
                                Text(
                                    f"Column: {col_name!r}",
                                    style=Style.chain(BOLD, CYAN),
                                )
                            )
                            yield self._create_column_stats_table(col_stats)

                        with Container(classes="sparkline-container"):
                            # Add sparkline for numeric columns
                            yield self._create_sparkline_comparison(col_name)
        else:
            yield Label(Text("No statistics available", style=DIM))

    def _create_column_stats_table(self, stats: SBSResult[ColStats]) -> Static:
        """Create statistics table for a column."""
        table = Table(box=None)
        table.add_column("Statistic", style=CYAN)
        table.add_column(self.diff_data.left.version, justify="right", style=DIM)
        table.add_column(self.diff_data.right.version, justify="left", style=DIM)
        table.add_column("Difference")

        # Handle numeric columns
        if isinstance(stats.left, NumericColStats) and isinstance(
            stats.right, NumericColStats
        ):
            for stat in ["mean", "std", "min", "max"]:
                val1 = getattr(stats.left, stat, "N/A")
                val2 = getattr(stats.right, stat, "N/A")

                diff = val2 - val1
                diff_str = f"{diff:+,.2f}"
                if stat == "mean" and val1 != 0:
                    pct_change = diff / val1
                    diff_str += f" ({pct_change:+,.1%})"

                table.add_row(
                    stat.capitalize(),
                    f"{val1:,.2f}" if isinstance(val1, int | float) else str(val1),
                    f"{val2:,.2f}" if isinstance(val2, int | float) else str(val2),
                    Text(
                        diff_str,
                        style=style_diff_frac(pct_change),
                    ),
                )

        # Add null counts
        table.add_row(
            "Null Count",
            f"{stats.left.null_count:,d}",
            f"{stats.right.null_count:,d}",
            f"{stats.right.null_count - stats.left.null_count:+,d}",
        )

        # Add unique count for string columns
        if isinstance(stats.left, StringColStats) and isinstance(
            stats.right, StringColStats
        ):
            table.add_row(
                "Unique Values",
                f"{stats.left.unique_count:,d}",
                f"{stats.right.unique_count:,d}",
                f"{stats.right.unique_count - stats.left.unique_count:+,d}",
            )

        return Static(table)

    def _create_sparkline_comparison(self, col_name: str) -> Container:
        """Create sparkline visualization for numeric column comparison."""
        # Attempt to get real sample data collected earlier
        left_df = (
            self.diff_data.comparison_result.details.sample_data_left
            if self.diff_data and self.diff_data.comparison_result
            else None
        )
        right_df = (
            self.diff_data.comparison_result.details.sample_data_right
            if self.diff_data and self.diff_data.comparison_result
            else None
        )

        left_col = left_df.get_column(col_name, default=None)
        right_col = right_df.get_column(col_name, default=None)

        if (left_col is None) and (right_col is None):
            return Static(Label(Text("Distribution unavailable", style=DIM)))

        if left_col.dtype.is_numeric() and right_col.dtype.is_numeric():

            def _extract_numeric(vals: pl.Series) -> list[float] | None:
                if vals.dtype.is_numeric():
                    return vals.drop_nulls().to_list()
                return None

            data1 = None if (left_col is None) else _extract_numeric(left_col)
            data2 = None if (right_col is None) else _extract_numeric(right_col)

        elif left_col.dtype == pl.String and right_col.dtype == pl.String:
            categories = sorted(
                set(left_col.drop_nulls().to_list())
                | set(right_col.drop_nulls().to_list())
            )
            data1 = (
                None
                if (left_col is None)
                else left_col.drop_nulls().map_elements(categories.index).to_list()
            )
            data2 = (
                None
                if (right_col is None)
                else right_col.drop_nulls().map_elements(categories.index).to_list()
            )

        # If we don't have real sample data, skip sparkline.
        if not (data1 and data2):
            return Static(Label(Text("Distribution unavailable", style=DIM)))
            # return Container()

        def _to_hist(values: list[float], bins: int = 40) -> list[int]:
            if len(values) == 0:
                return [0] * bins
            counts, _ = np.histogram(values, bins=min(bins, len(np.unique(values))))
            return counts.tolist()

        hist1 = None if (data1 is None) else _to_hist(data1)
        hist2 = None if (data2 is None) else _to_hist(data2)

        # return Container(
        return Horizontal(
            Vertical(
                Label(
                    Text(
                        f"{self.diff_data.left.version}",
                        style=BOLD,
                        justify="right",
                    )
                ),
                Sparkline(hist1),
            ),
            Vertical(
                Label(
                    Text(
                        f"{self.diff_data.right.version}",
                        style=BOLD,
                        justify="left",
                    )
                ),
                Sparkline(hist2),
            ),
            classes="sparkline-group",
        )
        #     classes="sparkline-container",
        # )


class ProgressModal(ModalScreen):
    """Modal screen showing progress."""

    def __init__(self, message: str = "Loading...") -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Container(classes="progress-modal"):
            yield Label(self.message)
            yield ProgressBar()
            yield LoadingIndicator()


class InteractiveDiffApp(App):
    """Interactive artifact diff application."""

    CSS = """
    Screen {
        background: $background;
    }

    .file-trees {
        height: 100%;
    }

    .tree-container {
        width: 50%;
        padding: 1;
        border: round $primary-background-darken-1;
        background: $panel;
    }

    .file-tree {
        width: 100%;
        scrollbar-size: 1 1;
    }

    Tree:focus {
        border: round $accent;
    }

    .section-title {
        padding: 0 1;
        text-align: center;
        text-style: bold;
        background: $primary-background-darken-1;
        color: $text;
    }

    .summary-stats {
        padding: 0;
        align: center middle;
    }

    .schema-changes {
        padding: 0;
        background: $panel;
        margin: 0 1;
    }

    .data-preview {
        /* auto height so summary below remains visible */
        padding: 0 1;
    }

    .data-table-container {
        width: 50%;
        height: 20;
        border: round $primary;
        margin: 0 1;
        background: $panel;
    }

    .column-stats {
        padding: 0 1;
        margin: 0 1;
        background: $panel;
    }

    .sparkline-container {
        padding: 0 1;
        margin: 0 1;
    }

    .stats-scroll {
        height: 50;
        border: round $primary-background-darken-1;
        margin: 0 1;
        background: $panel;
    }

    .progress-modal {
        align: center middle;
        background: $surface;
        border: thick $primary;
        padding: 2;
        width: 50;
        height: 11;
    }

    DataTable {
        height: 100%;
        scrollbar-background: $primary-background-darken-1;
        scrollbar-background-hover: $primary-background-darken-2;
        scrollbar-color: $primary;
        scrollbar-color-active: $accent;
    }

    DataTable:focus {
        border: round $accent;
    }

    #data-filter {
        margin: 0 1;
        width: 100%;
    }

    TabPane {
        padding: 0 1;
    }

    TabbedContent {
        background: $panel;
    }

    Header {
        background: $primary;
    }

    Footer {
        background: $primary-background-darken-1;
    }

    Label {
        width: 100%;
    }

    LoadingIndicator {
        color: $accent;
    }

    ProgressBar {
        width: 40;
    }

    ProgressBar Bar {
        background: $accent;
    }

    ProgressBar Percentage {
        color: $text;
    }

    Sparkline {
        margin: 1;
        width: 40;
        height: 3;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f", "toggle_filter", "Filter"),
        Binding("s", "save_report", "Save Report"),
        Binding("r", "refresh", "Refresh"),
        Binding("?", "help", "Help"),
        Binding("[", "focus_left", "Left Pane"),
        Binding("]", "focus_right", "Right Pane"),
        Binding("t", "toggle_file_filter", "Files: All/Δ/≡"),
    ]

    def __init__(
        self,
        art1_path: str,
        art2_path: str,
        diff_data: bool = True,
        # sample_size: int = 100,
        sample_size: int | None = None,
    ):
        super().__init__()
        self.art1_path = art1_path
        self.art2_path = art2_path
        self.diff_data_flag = diff_data
        self.sample_size = sample_size
        self.diff_data: DiffData | None = None
        self.api = Api()

    def compose(self) -> ComposeResult:
        yield Header()

        with TabbedContent():
            with TabPane("File Structure", id="files"):
                yield Container(id="file-tree-container")

            with TabPane("Data Comparison", id="data"):
                yield Container(id="data-comparison-container")

        yield Footer()

    async def on_mount(self) -> None:
        """Load data when app starts."""
        self.load_diff_data()

    @work(exclusive=True)
    async def load_diff_data(self) -> None:
        """Load artifact data and compute differences."""
        progress = ProgressModal("Loading artifacts...")
        self.push_screen(progress)

        try:
            # Load artifacts
            self.diff_data = await self._load_artifacts()

            # Update UI with loaded data
            await self._update_ui()

        finally:
            self.pop_screen()

    async def _load_artifacts(self) -> DiffData:
        """Load artifacts and compute differences."""
        # Fetch artifacts
        art_a = self.api.artifact(self.art1_path)
        art_b = (
            self.api.artifact(self.art2_path)
            if self.art2_path
            else _get_previous_version(art_a)
        )

        if not art_b:
            raise ValueError("No previous version found")

        # Determine which artifact is newer (higher version number)
        def _ver_int(artifact: Artifact) -> int:
            with suppress(Exception):
                return int(str(artifact.version).lstrip("v"))
            return 0

        if _ver_int(art_a) > _ver_int(art_b):
            newer, older = art_a, art_b
        else:
            newer, older = art_b, art_a

        # Left pane = older, Right pane = newer (per UX request)
        diff_data = DiffData(
            left=older, right=newer, tree_diff=ArtifactTreeDiff(older, newer)
        )

        # Load data comparison if requested
        if self.diff_data_flag:
            # Download artifacts
            diff_data.left_root = Path(art_a.download())
            diff_data.right_root = Path(art_b.download())

            # Compare data
            comparator = TableComparator()
            paths1 = sorted(p for p in diff_data.left_root.rglob("*") if p.is_file())
            paths2 = sorted(p for p in diff_data.right_root.rglob("*") if p.is_file())

            try:
                diff_data.comparison_result = comparator.compare(
                    paths1, paths2, self.sample_size
                )

                # Load sample data for preview
                await self._load_sample_data(diff_data)
            except Exception as e:
                self.notify(f"Failed to compare data: {e}", severity="warning")

        return diff_data

    async def _load_sample_data(self, diff_data: DiffData) -> None:
        """Load sample data for preview."""
        if not (
            (cmp_result := diff_data.comparison_result)
            and (samples := cmp_result.details.sample_comparison)
        ):
            return

        # Store the sample data
        diff_data.comparison_result.details.sample_data_left = samples.left
        # if isinstance(samples.left, pl.DataFrame):
        #     diff_data.comparison_result.details.sample_data_left = samples.left

        diff_data.comparison_result.details.sample_data_right = samples.right
        # if isinstance(samples.right, pl.DataFrame):
        #     diff_data.comparison_result.details.sample_data_right = samples.right

    async def _update_ui(self) -> None:
        """Update UI with loaded data."""
        if not self.diff_data:
            return

        # Update file tree
        file_container = self.query_one("#file-tree-container")
        file_container.remove_children()
        await file_container.mount(FileTreeDiffView(self.diff_data))

        # Update data comparison (now also houses statistics)
        data_container = self.query_one("#data-comparison-container")
        data_container.remove_children()
        await data_container.mount(DataComparisonView(self.diff_data))

        # Populate data tables if we have sample data
        if self.diff_data.comparison_result:
            await self._populate_data_tables()

    INITIAL_ROW_LIMIT = None

    async def _populate_data_tables(self) -> None:
        """Populate the data preview tables."""
        # result = self.diff_data.comparison_result

        if not (
            (result := self.diff_data.comparison_result) and (details := result.details)
        ):
            return

        # Get sample data
        left_data = details.sample_data_left
        right_data = details.sample_data_right

        # if not isinstance(left_data, pl.DataFrame) or not isinstance(
        #     right_data, pl.DataFrame
        # ):
        if (left_data is None) or (right_data is None):
            return

        # Populate left table
        try:
            table1 = self.query_one("#data1", FilterableDataTable)
            table1.clear()

            # Add columns
            table1.add_columns(*left_data.columns)

            # for col in left_data.columns:
            #     table1.add_column(col)

            # Add rows
            table1.original_data = tuple(left_data.iter_rows())
            for row in table1.original_data[
                : self.INITIAL_ROW_LIMIT
            ]:  # Limit initial display
                table1.add_row(*map(format_cell, row))
        except Exception:
            pass

        # Populate right table
        try:
            table2 = self.query_one("#data2", FilterableDataTable)
            table2.clear()

            # Add columns
            table2.add_columns(*right_data.columns)

            # for col in right_data.columns:
            #     table2.add_column(col)

            # Add rows
            table2.original_data = tuple(right_data.iter_rows())
            for row in table2.original_data[
                : self.INITIAL_ROW_LIMIT
            ]:  # Limit initial display
                table2.add_row(*map(format_cell, row))
        except Exception:
            pass

    def action_save_report(self) -> None:
        """Save diff report to file."""
        if not self.diff_data:
            self.notify("No data to save", severity="error")
            return

        # Generate report
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_fpath = f"artifact_diff_{timestamp}.json"

        report = {
            "timestamp": timestamp,
            "left": {
                "name": self.diff_data.left.qualified_name,
                "version": self.diff_data.left.version,
                "size": self.diff_data.left.size,
            },
            "right": {
                "name": self.diff_data.right.qualified_name,
                "version": self.diff_data.right.version,
                "size": self.diff_data.right.size,
            },
            "file_changes": {
                "added": [],
                "removed": [],
                "modified": [],
            },
            "data_summary": {},
        }

        # Analyze file changes
        paths1 = set(self.diff_data.left.manifest.entries)
        paths2 = set(self.diff_data.right.manifest.entries)

        report["file_changes"]["added"] = list(paths2 - paths1)
        report["file_changes"]["removed"] = list(paths1 - paths2)

        for path in paths1 & paths2:
            entry1 = self.diff_data.left.manifest.entries[path]
            entry2 = self.diff_data.right.manifest.entries[path]
            if entry1.digest != entry2.digest:
                report["file_changes"]["modified"].append(path)

        # Add data comparison summary if available
        if self.diff_data.comparison_result:
            if self.diff_data.comparison_result.summary.rows:
                report["data_summary"]["rows"] = (
                    self.diff_data.comparison_result.summary.rows
                )
            if self.diff_data.comparison_result.summary.schema:
                schema = self.diff_data.comparison_result.summary.schema
                report["data_summary"]["schema"] = {
                    "added_columns": schema.added_columns,
                    "removed_columns": schema.removed_columns,
                    "type_changes": {
                        k: dict(v) for k, v in schema.type_changes.items()
                    },
                }

        # Save to file
        try:
            with open(output_fpath, "w") as f:
                json.dump(report, f, indent=2)
        except Exception as e:
            self.notify(f"Failed to save report: {e}", severity="error")
        else:
            self.notify(f"Report saved to {output_fpath}", severity="information")

    def action_refresh(self) -> None:
        """Refresh the diff data."""
        self.notify("Refreshing...")
        # The `@work` decorator already schedules `load_diff_data` as a worker,
        # so calling it directly is sufficient.
        self.load_diff_data()

    def action_help(self) -> None:
        """Show help."""
        help_text = """
        [bold]Keyboard Shortcuts:[/bold]

        q - Quit
        f - Toggle filter
        s - Save report
        r - Refresh data
        ? - Show this help
        t - Cycle file view (all, changes, unchanged)

        Tab - Switch between views
        ↑/↓ - Navigate
        Enter - Expand/collapse tree nodes
        """
        self.notify(help_text, timeout=10)

    # ---------------------------------------------------------------------
    # Pane–focusing helpers
    # ---------------------------------------------------------------------

    def action_focus_left(self) -> None:
        """Focus the left file-tree pane (tree1)."""
        with suppress(Exception):  # Silently ignore if not present
            tree = self.query_one(f"#{FileTreeDiffView.ID_LEFT}", Tree)
            tree.focus()

    def action_focus_right(self) -> None:
        """Focus the right file-tree pane (tree2)."""
        with suppress(Exception):  # Silently ignore if not present
            tree = self.query_one(f"#{FileTreeDiffView.ID_RIGHT}", Tree)
            tree.focus()

    # ---------------------------------------------------------------------
    # File filter cycling
    # ---------------------------------------------------------------------

    def action_toggle_file_filter(self) -> None:
        """Cycle between file filter modes on the file-structure tab."""
        # Only act if we are on the File Structure tab
        current_tab = self.query_one(TabbedContent).active
        if current_tab != "files":
            return

        file_view = self.query(FileTreeDiffView).first()
        if not file_view:
            return

        file_view.filter_mode = file_view.filter_mode.next()
        file_view._build_trees()

        # Notify user of new mode
        self.notify(f"File filter: {file_view.filter_mode.value}")

    # ---------------------------------------------------------------------
    # Version change handling
    # ---------------------------------------------------------------------

    @on(VersionSelector.VersionChosen)
    async def _version_chosen(self, message: VersionSelector.VersionChosen) -> None:  # type: ignore
        """Handle user selecting a new version on either side."""
        side = message.side  # "left" or "right"
        version = message.version

        try:
            current_art = (
                self.diff_data.left if (side is _Side.LEFT) else self.diff_data.right
            )
            collection = current_art.collection
            new_art = next(a for a in collection.artifacts() if a.version == version)
        except Exception as e:  # pragma: no cover
            self.notify(f"Failed to load version {version}: {e}", severity="error")
            return

        other_art = (
            self.diff_data.right if (side is _Side.LEFT) else self.diff_data.left
        )

        # Decide ordering: older on left, newer on right
        def _v_int(a: Artifact) -> int:
            with suppress(Exception):
                return int(str(a.version).lstrip("v"))
            return 0

        if side is _Side.LEFT:
            cand_left, cand_right = new_art, other_art
        else:
            cand_left, cand_right = other_art, new_art

        # Ensure ordering rule
        if _v_int(cand_left) > _v_int(cand_right):
            cand_left, cand_right = cand_right, cand_left

        # Recompute diff_data
        new_diff = DiffData(
            left=cand_left,
            right=cand_right,
            tree_diff=ArtifactTreeDiff(cand_left, cand_right),
        )

        if self.diff_data_flag:
            comparator = TableComparator()
            new_diff.left_root = Path(cand_left.download())
            new_diff.right_root = Path(cand_right.download())

            paths1 = sorted(p for p in new_diff.left_root.rglob("*") if p.is_file())
            paths2 = sorted(p for p in new_diff.right_root.rglob("*") if p.is_file())

            try:
                new_diff.comparison_result = comparator.compare(
                    paths1, paths2, self.sample_size
                )

                await self._load_sample_data(new_diff)
            except Exception as e:  # pragma: no cover
                self.notify(f"Failed to compare data: {e!s}", severity="warning")

        self.diff_data = new_diff

        await self._update_ui()


def run_interactive_diff(
    artifact1: str,
    artifact2: str | None = None,
    diff_data: bool = True,
    sample_size: int | None = None,
) -> None:
    """Run the interactive diff application."""
    app = InteractiveDiffApp(
        art1_path=artifact1,
        art2_path=artifact2 or "",
        diff_data=diff_data,
        sample_size=sample_size,
    )
    app.run()


# Future Enhancement Ideas:
# ========================
#
# 1. Advanced Filtering:
#    - Regex support for data filtering
#    - Column-specific filters
#    - Save/load filter presets
#
# 2. File Content Viewer:
#    - Side-by-side file content comparison
#    - Syntax highlighting for code files
#    - Binary file preview (images, etc.)
#
# 3. Enhanced Visualizations:
#    - Interactive Plotly charts in terminal
#    - Heatmaps for correlation changes
#    - Time series comparison for temporal data
#
# 4. Collaboration Features:
#    - Share diff reports via W&B
#    - Add comments to specific changes
#    - Generate PR-style reviews
#
# 5. Performance Optimizations:
#    - Streaming comparison for huge files
#    - Parallel processing for multiple files
#    - Incremental loading UI
#
# 6. Integration Features:
#    - Export to various formats (HTML, PDF, Markdown)
#    - CI/CD integration for automatic artifact validation
#    - Slack/Discord notifications for significant changes
#
# 7. Smart Diffing:
#    - ML model weight comparison
#    - Dataset distribution shift detection
#    - Automatic anomaly highlighting
#
# 8. Customization:
#    - User-defined comparison algorithms
#    - Custom color schemes
#    - Plugin system for data type handlers
