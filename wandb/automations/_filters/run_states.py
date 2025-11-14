from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BeforeValidator
from typing_extensions import Annotated

from wandb._iterutils import always_list
from wandb._pydantic import GQLBase, field_validator
from wandb.automations._validators import LenientStrEnum

from .expressions import FilterExpr
from .operators import BaseOp

if TYPE_CHECKING:
    from wandb.automations.events import EventType, RunStateFilter


class ReportedRunState(LenientStrEnum):  # from: StateToReport
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    FAILED = "FAILED"

    # Convenience aliases that are equivalent when *creating* or *editing*
    # the triggering event for a run state automation.
    # NOTE: These may still be reported as distinct values from an *executed* automation.
    CRASHED = FAILED


class StateFilter(GQLBase):  # from: RunStateFilter
    states: Annotated[
        list[ReportedRunState],
        BeforeValidator(always_list),  # Coerce x -> [x] if passed a single value
    ]

    @property
    def event_type(self) -> EventType:
        return EventType.RUN_STATE

    @field_validator("states", mode="after")
    @classmethod
    def _dedup_and_order(cls, v: list[ReportedRunState]) -> list[ReportedRunState]:
        """Ensure states are deduplicated and predictably ordered."""
        return sorted(set(v))

    def __and__(self, other: Any) -> RunStateFilter:
        """Returns `(state_filter & run_filter)` as a `RunStateFilter`."""
        from wandb.automations.events import RunStateFilter

        if isinstance(run_filter := other, (BaseOp, FilterExpr)):
            # Treat `other` as a run filter and build a RunStateFilter. Let the
            # metric filter validators wrap or nest as appropriate.
            return RunStateFilter(run=run_filter, state=self)
        return NotImplemented

    def __rand__(self, other: BaseOp | FilterExpr) -> RunStateFilter:
        """Ensures `&` is commutative for run and state filters.

        I.e. `(run_filter & state_filter) == (state_filter & run_filter)`.
        """
        return self.__and__(other)
