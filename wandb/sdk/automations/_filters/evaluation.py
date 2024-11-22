from __future__ import annotations

from typing import ClassVar

from wandb.sdk.automations._filters.base import Op


class Regex(Op):
    op: ClassVar[str] = "$regex"

    inner_operand: str  #: The regex expression to match against.


class Contains(Op):
    op: ClassVar[str] = "$contains"
    # NOTE: `$contains` isn't formally supported by MongoDB, but it is recognized
    # as a substring-match filter in the backend

    inner_operand: str  #: The substring to match against.
