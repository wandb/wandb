from __future__ import annotations

from typing import ClassVar

from .base import Op


class Regex(Op):
    OP: ClassVar[str] = "$regex"
    other: str  #: The regex expression to match against.


class Contains(Op):
    # Not an actual MongoDB operator, but the backend treats this as a substring-match filter.
    OP: ClassVar[str] = "$contains"
    other: str  #: The substring to match against.
