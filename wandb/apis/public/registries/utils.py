from typing import Mapping, Sequence

from wandb.sdk.artifacts._validators import REGISTRY_PREFIX


def _ensure_registry_prefix_on_names(query, in_name=False):
    """Traverse the filter to prepend the `name` key value with the registry prefix unless the value is a regex.

    - in_name: True if we are under a "name" key (or propagating from one).

    EX: {"name": "model"} -> {"name": "wandb-registry-model"}
    """
    if isinstance((txt := query), str):
        if in_name:
            return txt if txt.startswith(REGISTRY_PREFIX) else f"{REGISTRY_PREFIX}{txt}"
        return txt
    if isinstance((dct := query), Mapping):
        new_dict = {}
        for key, obj in dct.items():
            if key == "name":
                new_dict[key] = _ensure_registry_prefix_on_names(obj, in_name=True)
            elif key == "$regex":
                # For regex operator, we skip transformation of its value.
                new_dict[key] = obj
            else:
                # For any other key, propagate the in_name and skip_transform flags as-is.
                new_dict[key] = _ensure_registry_prefix_on_names(obj, in_name=in_name)
        return new_dict
    if isinstance((objs := query), Sequence):
        return list(
            map(lambda x: _ensure_registry_prefix_on_names(x, in_name=in_name), objs)
        )
    return query
