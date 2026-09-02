from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from google.protobuf.internal.containers import RepeatedCompositeFieldContainer


def dict_from_proto_list(obj_list: RepeatedCompositeFieldContainer) -> dict[str, Any]:
    result: dict[str, Any] = {}

    for item in obj_list:
        # Start from the root of the result dict
        current_level = result

        if len(item.nested_key) > 0:
            keys = list(item.nested_key)
        else:
            keys = [item.key]

        for key in keys[:-1]:
            if key not in current_level:
                current_level[key] = {}
            # Move the reference deeper into the nested dictionary
            current_level = current_level[key]

        # Set the value at the final key location, parsing JSON from the value_json field
        final_key = keys[-1]
        current_level[final_key] = json.loads(item.value_json)

    return result
