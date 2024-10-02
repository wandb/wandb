#
import json
from typing import TYPE_CHECKING, Any, Dict, Union

from wandb.proto import wandb_internal_pb2 as pb

if TYPE_CHECKING:  # pragma: no cover
    from google.protobuf.internal.containers import RepeatedCompositeFieldContainer
    from google.protobuf.message import Message

    from wandb.proto import wandb_telemetry_pb2 as tpb


def dict_from_proto_list(obj_list: "RepeatedCompositeFieldContainer") -> Dict[str, Any]:
    result: Dict[str, Any] = {}

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


def _result_from_record(record: "pb.Record") -> "pb.Result":
    result = pb.Result(uuid=record.uuid, control=record.control)
    return result


def _assign_record_num(record: "pb.Record", record_num: int) -> None:
    record.num = record_num


def _assign_end_offset(record: "pb.Record", end_offset: int) -> None:
    record.control.end_offset = end_offset


def proto_encode_to_dict(
    pb_obj: Union["tpb.TelemetryRecord", "pb.MetricRecord"],
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
                if items:
                    data[desc.number] = items
            else:
                # TODO: for now this code only handles sub-messages with strings
                md = {}
                for d, v in nested:
                    if not v or d.type != d.TYPE_STRING:
                        continue
                    md[d.number] = v
                data[desc.number] = md
    return data


def message_to_dict(
    message: "Message",
) -> Dict[str, Any]:
    """Convert a protobuf message into a dictionary."""
    from google.protobuf.json_format import MessageToDict

    return MessageToDict(message, preserving_proto_field_name=True)
