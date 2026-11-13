from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from wandb._filters import FilterExpr, In
from wandb._iterutils import always_list
from wandb.automations._validators import LenientStrEnum


class SandboxState(LenientStrEnum):  # from: SandboxState in the W&B server
    """A state a sandbox can reach that triggers a sandbox automation."""

    CREATED = "CREATED"
    """The sandbox was placed and is starting."""

    COMPLETED = "COMPLETED"
    """The sandbox exited cleanly or was stopped."""

    FAILED = "FAILED"
    """The sandbox failed to start, exited with an error, or hit its maximum lifetime."""


class SandboxStateField:
    """Descriptor type, returned on accessing `SandboxEvent.state`.

    Only `==`, `eq()` and `in_()` are supported, and they always write a
    one-or-more-item `$in` of `SandboxState` values: the server compares states
    case-sensitively, and `$in` is the form the W&B App edits. To exclude a
    state, list the others.
    """

    def __get__(self, obj: Any, objtype: type) -> SandboxStateField:
        return self

    def eq(self, state: str | SandboxState, /) -> FilterExpr:
        """Returns a filter that watches for `state == state`."""
        return self.in_([state])

    def in_(self, states: Iterable[str | SandboxState], /) -> FilterExpr:
        """Returns a filter that watches for `state in states`."""
        normalized = sorted({SandboxState(s) for s in always_list(states)})
        return FilterExpr(field="state", op=In(val=normalized))

    def __eq__(self, other: Any) -> FilterExpr:  # type: ignore[override]
        if isinstance(other, str):
            return self.eq(other)
        raise TypeError(
            f"Invalid operand type in sandbox state filter: {type(other)!r}"
        )

    def __ne__(self, other: Any) -> FilterExpr:  # type: ignore[override]
        # Defined so `!=` raises instead of falling back to `not (self == other)`.
        raise TypeError(
            "Sandbox state filters only support `==` and `in_()`; "
            "to exclude a state, list the others with `in_()`"
        )

    __hash__ = None  # type: ignore[assignment]
