from __future__ import annotations

from typing import cast

from pydantic import Json
from pydantic_core import to_json

from wandb.sdk.automations._typing import T


def jsonify(obj: T) -> Json[T]:
    return cast(
        Json[T],
        to_json(obj, by_alias=True, round_trip=True, bytes_mode="utf8").decode("utf8"),
    )
