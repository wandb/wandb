from __future__ import annotations

import sys
from typing import TypeVar

from pydantic import Field

if sys.version_info >= (3, 12):
    from typing import Annotated
else:
    from typing_extensions import Annotated

Base64Id = Annotated[str, Field(repr=False, strict=True)]  # TODO: Fix this

NameT = TypeVar("NameT", bound=str)

Typename = Annotated[
    NameT,
    Field(repr=False, alias="__typename", frozen=True),
]
