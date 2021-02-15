#
import json

import wandb


if wandb.TYPE_CHECKING:
    from typing import Any, Dict, Union
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:  # pragma: no cover
        from wandb.proto import wandb_internal_pb2 as pb
        from wandb.proto import wandb_telemetry_pb2 as tpb


def dict_from_proto_list(obj_list):
    d = dict()
    for item in obj_list:
        d[item.key] = json.loads(item.value_json)
    return d


def proto_encode_to_dict(
    pb_obj: Union["tpb.TelemetryRecord", "pb.MetricRecord"]
) -> Dict[int, Any]:
    data: Dict[int, Any] = dict()
    fields = pb_obj.ListFields()
    for desc, value in fields:
        if desc.name.startswith("_"):
            continue
        if desc.type == desc.TYPE_STRING:
            data[desc.number] = value
        elif desc.type == desc.TYPE_INT32:
            data[desc.number] = value
        elif desc.type == desc.TYPE_ENUM:
            data[desc.number] = value
        elif desc.type == desc.TYPE_MESSAGE:
            nested = value.ListFields()
            bool_msg = all(d.type == d.TYPE_BOOL for d, _ in nested)
            if bool_msg:
                items = [d.number for d, v in nested if v]
                data[desc.number] = items
    return data
