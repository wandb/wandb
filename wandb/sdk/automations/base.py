from abc import ABC
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from pydantic.main import IncEx


class Base(BaseModel, ABC):
    """Abstract base class for all automation classes/types."""

    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
        use_enum_values=True,
    )

    def model_dump(
        self,
        *,
        mode: Literal["json", "python"] | str = "python",
        include: IncEx = None,
        exclude: IncEx = None,
        context: dict[str, Any] | None = None,
        by_alias: bool = True,  # NOTE: changed default
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        round_trip: bool = True,  # NOTE: changed default
        warnings: bool | Literal["none", "warn", "error"] = True,
        serialize_as_any: bool = False,
    ) -> dict[str, Any]:
        return super().model_dump(
            mode=mode,
            include=include,
            exclude=exclude,
            context=context,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            round_trip=round_trip,
            warnings=warnings,
            serialize_as_any=serialize_as_any,
        )
