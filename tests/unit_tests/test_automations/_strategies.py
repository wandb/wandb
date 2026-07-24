"""Example generation strategies for automations tests that rely on `hypothesis`."""

from __future__ import annotations

from enum import Enum
from secrets import choice
from string import ascii_letters
from typing import Any

from hypothesis.strategies import (
    DrawFn,
    SearchStrategy,
    booleans,
    composite,
    dictionaries,
    floats,
    integers,
    just,
    lists,
    none,
    one_of,
    recursive,
    sampled_from,
    text,
)
from wandb._strutils import b64encode_ascii
from wandb.automations import (
    MetricChangeFilter,
    MetricThresholdFilter,
    MetricZScoreFilter,
)
from wandb.automations._run_metric_filters import Agg, ChangeDir, ChangeType
from wandb.automations._run_state_filters import ReportedRunState

from ..test_filters._strategies import PRINTABLE_CHARS, ints_or_floats


@composite
def gql_ids(
    draw: DrawFn,
    prefix: str | SearchStrategy[str] | None = None,
) -> SearchStrategy[str]:
    """GraphQL IDs as base64-encoded strings."""
    if prefix is None:
        prefix = text(ascii_letters)

    name = draw(prefix) if isinstance(prefix, SearchStrategy) else prefix

    index = draw(integers(min_value=0, max_value=1_000_000))
    return b64encode_ascii(f"{name}:{index:d}")


def jsonables() -> SearchStrategy[Any]:
    """JSON-serializable objects."""
    jsonable_scalars = none() | booleans() | ints_or_floats | text()
    return recursive(
        jsonable_scalars,
        extend=lambda xs: lists(xs) | dictionaries(text(), xs),
    )


# ----------------------------------------------------------------------------
def randomcase(s: str) -> str:
    """Randomize the case of each character in the given string."""
    return "".join(choice([str.lower, str.upper])(c) for c in s)


@composite
def sample_with_randomcase(
    draw: DrawFn,
    obj: str | type[Enum],
) -> SearchStrategy[str | Enum]:
    """Generate the original string and enum value(s) in addition to random-case string variants."""
    if isinstance(obj, type) and issubclass(obj, Enum):
        # Sample from the original enum members, the string values, and its
        # randomly-cased variants
        orig_enums = sampled_from(obj)
        orig_values = sampled_from(list(s.value for s in obj))
        return draw(orig_enums | orig_values | orig_values.map(randomcase))
    if isinstance(obj, str):
        orig_strings = just(obj)
        return draw(orig_strings | orig_strings.map(randomcase))
    raise ValueError(f"Invalid object type: {type(obj).__name__}")


# ----------------------------------------------------------------------------
# For testing run metric filters
metric_names: SearchStrategy[str] = text(
    PRINTABLE_CHARS, min_size=1, max_size=100
).filter(lambda s: s[0].isalpha())
"""Valid metric names for run metric filters."""

cmp_keys: SearchStrategy[str] = sampled_from(["$gt", "$gte", "$lt", "$lte"])
"""Valid keys for MongoDB comparison operators."""

window_sizes: SearchStrategy[int] = integers(min_value=1, max_value=100)
"""Valid window sizes for run metric filters."""

aggs: SearchStrategy[Agg | str | None] = none() | sample_with_randomcase(Agg)
change_types: SearchStrategy[ChangeType | str] = sample_with_randomcase(ChangeType)
change_dirs: SearchStrategy[ChangeDir | str] = sample_with_randomcase(ChangeDir)
run_states: SearchStrategy[ReportedRunState | str] = sample_with_randomcase(
    ReportedRunState
)


pos_numbers: SearchStrategy[int | float] = one_of(
    integers(min_value=1),
    floats(
        min_value=0,
        exclude_min=True,
        width=32,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    ),
)
"""Valid "change_amount" values (i.e. `frac` or `diff`)."""

nonpos_numbers: SearchStrategy[int | float] = one_of(
    integers(max_value=0),
    floats(
        max_value=0,
        width=32,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    ),
)
"""Invalid "change_amount" values (i.e. `frac` or `diff`)."""

neg_numbers: SearchStrategy[int | float] = one_of(
    integers(max_value=-1),
    floats(
        max_value=0,
        exclude_max=True,
        width=32,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    ),
)
"""Valid negative threshold values for zscore < operator."""


@composite
def metric_threshold_filters(
    draw: DrawFn,
    name: SearchStrategy[str] | None = metric_names,
    agg: SearchStrategy[Agg | str | None] | None = aggs,
    window: SearchStrategy[int] | None = window_sizes,
    cmp: SearchStrategy[str] | None = cmp_keys,
    threshold: SearchStrategy[float] | None = ints_or_floats,
) -> SearchStrategy[MetricThresholdFilter]:
    """Generates a `MetricThresholdFilter` instance."""
    kw_strategies = dict(
        name=name,
        window=window,
        agg=agg,
        cmp=cmp,
        threshold=threshold,
    )
    kwargs = {k: draw(st) for k, st in kw_strategies.items() if (st is not None)}
    return MetricThresholdFilter(**kwargs)


@composite
def metric_change_filters(
    draw: DrawFn,
    name: SearchStrategy[str] | None = metric_names,
    agg: SearchStrategy[Agg | str | None] | None = aggs,
    window: SearchStrategy[int] | None = window_sizes,
    prior_window: SearchStrategy[int] | None = window_sizes,
    change_type: SearchStrategy[ChangeType | str] | None = change_types,
    change_dir: SearchStrategy[ChangeDir | str] | None = change_dirs,
    threshold: SearchStrategy[float] | None = pos_numbers,
    # **kwargs: SearchStrategy[Any],
) -> SearchStrategy[MetricChangeFilter]:
    """Generates a `MetricChangeFilter` instance."""
    kw_strategies = dict(
        name=name,
        agg=agg,
        window=window,
        prior_window=prior_window,
        change_type=change_type,
        change_dir=change_dir,
        threshold=threshold,
    )
    # Any arg strategies `None` excluded from instantiation
    kwargs = {k: draw(st) for k, st in kw_strategies.items() if (st is not None)}
    return MetricChangeFilter(**kwargs)


@composite
def metric_zscore_filters(
    draw: DrawFn,
    name: SearchStrategy[str] | None = metric_names,
    window_size: SearchStrategy[int] | None = window_sizes,
    threshold: SearchStrategy[float] | None = pos_numbers,
    change_dir: SearchStrategy[ChangeDir | str] | None = change_dirs,
) -> SearchStrategy[MetricZScoreFilter]:
    """Generates a `MetricZScoreFilter` instance."""
    kw_strategies = dict(
        name=name,
        window=window_size,
        threshold=threshold,
        change_dir=change_dir,
    )
    # Any arg strategies `None` excluded from instantiation
    kwargs = {k: draw(st) for k, st in kw_strategies.items() if (st is not None)}
    return MetricZScoreFilter(**kwargs)
