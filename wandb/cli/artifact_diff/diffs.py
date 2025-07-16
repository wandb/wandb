from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Self, assert_never

import plotly.graph_objects as go
import polars as pl
import polars.selectors as cs
from humanize import naturalsize
from more_itertools import always_iterable, map_except
from pydantic import ConfigDict, Field, NonNegativeInt
from pydantic.dataclasses import dataclass
from rich.columns import Columns
from rich.console import Console, JustifyMethod, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from wandb import Artifact

from .utils import (
    BOLD_BLUE,
    BRIGHT_GREEN,
    BRIGHT_RED,
    DIM,
    GREEN,
    RED,
    RED_DIM,
    YELLOW,
    ColName,
)

console = Console()


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class SBSResult[T]:
    left: T
    right: T


@dataclass
class SchemaInfo:
    added_columns: list[ColName]
    removed_columns: list[ColName]
    type_changes: dict[ColName, ColumnTypeChange]
    total_columns: SBSResult[int]


@dataclass
class ColumnTypeChange(SBSResult[str]):
    left: str
    right: str


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class ComparisonResultSummary:
    schema: SchemaInfo | None = None
    rows: RowCountInfo | None = None


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class RowCountInfo(SBSResult[NonNegativeInt]):
    left: NonNegativeInt
    right: NonNegativeInt

    @property
    def diff(self) -> int:
        return self.right - self.left

    @property
    def pct_change(self) -> float | None:
        return (self.diff / self.left) * 100 if (self.left > 0) else None


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class ComparisonResultDetails:
    column_stats: dict[ColName, SBSResult[ColStats]] | None = None

    sample_comparison: SBSResult[pl.DataFrame] | None = None
    sample_data_left: pl.DataFrame | None = None
    sample_data_right: pl.DataFrame | None = None


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class ComparisonResult:
    summary: ComparisonResultSummary = Field(default_factory=ComparisonResultSummary)
    details: ComparisonResultDetails = Field(default_factory=ComparisonResultDetails)
    visualizations: list[Any] = Field(default_factory=list)

    def display(self):
        """Display the comparison results."""
        pass


class DataComparator(ABC):
    """Abstract base class for data comparators."""

    @abstractmethod
    def compare(self, left: Path, right: Path, sample_size: int) -> ComparisonResult:
        """Compare two files and return a comparison result."""
        raise NotImplementedError


class UnsupportedTableFileError(ValueError):
    """Raised when a table file is not supported."""


def read_anytable(path: str | Path) -> pl.DataFrame:
    match Path(path).suffix.lower():
        case ".csv":
            return pl.read_csv(path)
        case ".parquet":
            return pl.read_parquet(path)
        case ".jsonl" | ".ndjson":
            return pl.read_ndjson(path)
        case _:
            raise UnsupportedTableFileError(
                f"Unsupported file type {path.suffix!r} for: {path!s}"
            )


class TableComparator(DataComparator):
    """Compare CSV, Parquet, and other tabular data formats."""

    def load_data(self, path: str | Path | Iterable[str | Path]) -> pl.DataFrame:
        paths = always_iterable(path)
        return pl.concat(
            map_except(read_anytable, paths, UnsupportedTableFileError),
            how="diagonal",
        )

    def compare(
        self,
        left: str | Path | list[str | Path],
        right: str | Path | list[str | Path],
        sample_size: NonNegativeInt,
    ) -> ComparisonResult:
        # Load data
        df1 = self.load_data(left)
        df2 = self.load_data(right)

        result = ComparisonResult()

        # Schema comparison
        result.summary = ComparisonResultSummary(
            schema=_compare_schemas(df1, df2),
            # Row count comparison
            rows=RowCountInfo(left=len(df1), right=len(df2)),
        )

        # Column-level statistics comparison
        result.details.column_stats = _compare_column_stats(df1, df2)

        # Sampled data comparison
        if sample_size:
            result.details.sample_comparison = _compare_samples(df1, df2, sample_size)
        else:
            result.details.sample_comparison = SBSResult(
                left=df1,
                right=df2,
            )

        # Distribution comparison for numeric columns
        result.visualizations = self._create_distribution_comparisons(df1, df2)

        return result

    def _create_distribution_comparisons(
        self, left: pl.DataFrame, right: pl.DataFrame
    ) -> list:
        """Create distribution comparisons for numeric columns."""
        # Create a histogram for each numeric column
        histograms = []
        for col in left.select(cs.by_dtype(pl.Float64, pl.Int64)).columns:
            # Create histograms for both dataframes
            # hist1 = left[col].hist(bins=20)
            # hist2 = right[col].hist(bins=20)

            # Create a comparison plot
            fig = go.Figure()
            fig.add_trace(go.Histogram(x=left[col], name="File 1", opacity=0.7))
            fig.add_trace(go.Histogram(x=right[col], name="File 2", opacity=0.7))

            histograms.append(fig)

        return histograms


@dataclass
class NumericColStats:
    mean: float
    std: float
    min: float
    max: float
    null_count: int


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class StringColStats:
    unique_count: int
    null_count: int
    top_values: pl.DataFrame


type ColStats = NumericColStats | StringColStats


def _compare_column_stats(df1: pl.DataFrame, df2: pl.DataFrame) -> dict:
    """Compare statistical properties of columns."""
    stats = {}

    common_cols = set(df1.columns) & set(df2.columns)

    for col in common_cols:
        if df1[col].dtype.is_numeric():
            stats[col] = SBSResult(
                left=NumericColStats(
                    mean=df1[col].mean(),
                    std=df1[col].std(),
                    min=df1[col].min(),
                    max=df1[col].max(),
                    null_count=df1[col].null_count(),
                ),
                right=NumericColStats(
                    mean=df2[col].mean(),
                    std=df2[col].std(),
                    min=df2[col].min(),
                    max=df2[col].max(),
                    null_count=df2[col].null_count(),
                ),
            )

            # stats[col] = {
            #     "left": {
            #         "mean": df1[col].mean(),
            #         "std": df1[col].std(),
            #         "min": df1[col].min(),
            #         "max": df1[col].max(),
            #         "null_count": df1[col].null_count(),
            #     },
            #     "right": {
            #         "mean": df2[col].mean(),
            #         "std": df2[col].std(),
            #         "min": df2[col].min(),
            #         "max": df2[col].max(),
            #         "null_count": df2[col].null_count(),
            #     },
            # }

        elif df1[col].dtype == pl.String:
            stats[col] = SBSResult(
                left=StringColStats(
                    unique_count=df1[col].n_unique(),
                    null_count=df1[col].null_count(),
                    top_values=df1[col].value_counts().head(5),
                ),
                right=StringColStats(
                    unique_count=df2[col].n_unique(),
                    null_count=df2[col].null_count(),
                    top_values=df2[col].value_counts().head(5),
                ),
            )

            # stats[col] = {
            #     "left": {
            #         "unique_count": df1[col].n_unique(),
            #         "null_count": df1[col].null_count(),
            #         "top_values": df1[col].value_counts().head(5),
            #     },
            #     "right": {
            #         "unique_count": df2[col].n_unique(),
            #         "null_count": df2[col].null_count(),
            #         "top_values": df2[col].value_counts().head(5),
            #     },
            # }

    return stats


def _compare_samples(
    df1: pl.DataFrame, df2: pl.DataFrame, sample_size: int
) -> SBSResult[pl.DataFrame]:
    """Compare samples between two dataframes."""
    return SBSResult(
        left=df1.head(sample_size),
        right=df2.head(sample_size),
        # left=df1.sample(sample_size),
        # right=df2.sample(sample_size),
    )
    # return {
    #     "left": df1.sample(sample_size),
    #     "right": df2.sample(sample_size),
    # }


def _compare_schemas(df1: pl.DataFrame, df2: pl.DataFrame) -> SchemaInfo:
    """Compare schemas between two dataframes."""
    schema1 = dict(df1.schema)
    schema2 = dict(df2.schema)

    cols1 = set(schema1)
    cols2 = set(schema2)

    common_cols = sorted(cols1 & cols2)

    type_changes: dict[ColName, ColumnTypeChange] = {
        col: ColumnTypeChange(left=schema1[col], right=schema2[col])
        for col in common_cols
        if schema1[col] != schema2[col]
    }

    return SchemaInfo(
        added_columns=sorted(cols2 - cols1),
        removed_columns=sorted(cols1 - cols2),
        type_changes=type_changes,
        total_columns=SBSResult(left=len(schema1), right=len(schema2)),
    )


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class ArtifactTreeDiff:
    left: Artifact
    right: Artifact

    def build_file_tree(self) -> tuple[Tree, Tree]:
        """Build file trees for both artifacts with diff highlighting."""
        tree1 = Tree(
            Text(
                f"{self.left.qualified_name}",
                justify="right",
                style=BOLD_BLUE,
            )
        )
        tree2 = Tree(
            Text(
                f"{self.right.qualified_name}",
                justify="left",
                style=BOLD_BLUE,
            )
        )

        # Get all unique paths from both artifacts -- paths are manifest entry keys
        paths1 = set(self.left.manifest.entries)
        paths2 = set(self.right.manifest.entries)

        all_paths = paths1 | paths2

        # Build trees with highlighting
        for path in sorted(all_paths):
            in_v1 = path in paths1
            in_v2 = path in paths2

            # Color coding:
            # - Green: New in v2
            # - Red: Removed in v2
            # - Yellow: Modified (different size/digest)
            # - White: Unchanged

            if in_v1 and in_v2:
                entry1 = self.left.manifest.entries[path]
                entry2 = self.right.manifest.entries[path]

                if entry1.digest != entry2.digest:
                    style = YELLOW
                    extra_info = " [dim](modified)[/dim]"
                else:
                    style = ""
                    extra_info = None

                self._add_path_to_tree(
                    tree1,
                    path,
                    entry1.size,
                    info=extra_info,
                    style=style,
                    justify="right",
                )
                self._add_path_to_tree(
                    tree2,
                    path,
                    entry2.size,
                    info=extra_info,
                    style=style,
                    justify="left",
                )

            elif in_v1 and not in_v2:
                entry1 = self.left.manifest.entries[path]
                self._add_path_to_tree(
                    tree1,
                    path,
                    size=entry1.size,
                    info=None,
                    style=RED_DIM,
                    justify="right",
                )
                self._add_placeholder_to_tree(
                    tree2,
                    path,
                    placeholder=Text("=> removed", style=Style.chain(BRIGHT_RED, DIM)),
                    justify="left",
                )

            elif in_v2 and not in_v1:  # in_v2 and not in_v1
                entry2 = self.right.manifest.entries[path]
                self._add_placeholder_to_tree(
                    tree1,
                    path,
                    placeholder=Text(
                        "added =>",
                        style=Style.chain(BRIGHT_GREEN, DIM),
                        justify="right",
                    ),
                    justify="right",
                )
                self._add_path_to_tree(
                    tree2,
                    path,
                    size=entry2.size,
                    info=None,
                    style=GREEN,
                    justify="left",
                )
            else:
                assert_never(f"{in_v1=}, {in_v2=}")

        return tree1, tree2

    def display_side_by_side(self):
        """Display the two trees side by side."""
        tree1, tree2 = self.build_file_tree()

        # Create panels for each tree
        panel1 = Panel(tree1, title=f"{self.left.qualified_name}")
        panel2 = Panel(tree2, title=f"{self.right.qualified_name}")

        # Display side by side
        console.print(Columns([panel1, panel2], equal=True))

    def _add_path_to_tree(
        self,
        tree: Tree,
        path: str,
        size: int,
        info: str | None,
        style: str,
        justify: JustifyMethod,
    ):
        """Add a path to the tree with a specific style."""
        path_ = Path(path)

        # *parents, child = path.split("/")

        current_node = tree
        # for parent in parents:
        for parent in path_.parent.parts:
            if not current_node.children:
                current_node.add(Text(f"{parent}/", justify=justify))
            current_node = current_node.children[0]

        if info:
            display_text = f"{path_.name} {naturalsize(size)} {info}"
        else:
            display_text = f"{path_.name} {naturalsize(size)}"

        current_node.add(Text(display_text, style=style, justify=justify))

    def _add_placeholder_to_tree(
        self,
        tree: Tree,
        path: str,
        placeholder: RenderableType,
        justify: JustifyMethod,
    ):
        """Add a placeholder for a path that exists in one artifact but not the other."""
        *parents, _ = path.split("/")
        current_node = tree
        for parent in parents:
            if not current_node.children:
                current_node.add(Text(f"{parent}/", justify=justify))
            current_node = current_node.children[0]
        # current_node.add(Text(child, style=style, justify=justify))
        current_node.add(placeholder)


@dataclass
class DataDiff:
    result: ComparisonResult

    def display_summary_table(self) -> Self:
        """Display a summary table of differences."""
        table = Table(title="Data Comparison Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Version 1", style="blue")
        table.add_column("Version 2", style="green")
        table.add_column("Change", style="yellow")

        # Add rows
        row_info = self.result.summary.rows
        table.add_row(
            "Total Rows",
            f"{row_info.left:,}",
            f"{row_info.right:,}",
            f"{row_info.diff:+,} ({row_info.pct_change:+.1f}%)"
            if (row_info.pct_change is not None)
            else str(row_info.diff),
        )

        schema_info = self.result.summary.schema
        table.add_row(
            "Total Columns",
            str(schema_info.total_columns.left),
            str(schema_info.total_columns.right),
            f"{len(schema_info.added_columns)} added, {len(schema_info.removed_columns)} removed",
        )

        console.print(table)
        return self

    def display_schema_changes(self) -> Self:
        """Display schema changes in a clear format."""
        schema_info = self.result.summary.schema

        if added_columns := schema_info.added_columns:
            console.print("\n+ Added columns:", style=GREEN)
            for col in added_columns:
                console.print(f"  + {col!s}")

        if removed_columns := schema_info.removed_columns:
            console.print("\n- Removed columns:", style=RED)
            for col in removed_columns:
                console.print(f"  - {col!s}")

        if type_changes := schema_info.type_changes:
            console.print("\n~ Type changes:", style=YELLOW)
            for col, change in type_changes.items():
                console.print(f"  ~ {col!s}: {change.left} → {change.right}")
        return self
