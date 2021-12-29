#
import json
from typing import Any, Dict, Union
from typing import TYPE_CHECKING

from wandb.proto import wandb_internal_pb2 as pb

if TYPE_CHECKING:  # pragma: no cover
    from wandb.proto import wandb_server_pb2 as spb
    from wandb.proto import wandb_telemetry_pb2 as tpb
    from google.protobuf.internal.containers import MessageMap
    from google.protobuf.internal.containers import RepeatedCompositeFieldContainer


def dict_from_proto_list(obj_list: "RepeatedCompositeFieldContainer") -> Dict[str, Any]:
    d = dict()
    for item in obj_list:
        d[item.key] = json.loads(item.value_json)
    return d


def _result_from_record(record: "pb.Record") -> "pb.Result":
    result = pb.Result(uuid=record.uuid, control=record.control)
    return result


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


def settings_dict_from_pbmap(
    pbmap: "MessageMap[str, spb.SettingsValue]",
) -> Dict[str, Any]:
    d: Dict[str, Any] = dict()
    for k in pbmap:
        v_obj = pbmap[k]
        v_type = v_obj.WhichOneof("value_type")
        v: Union[int, str, float, None, tuple] = None
        if v_type == "int_value":
            v = v_obj.int_value
        elif v_type == "string_value":
            v = v_obj.string_value
        elif v_type == "float_value":
            v = v_obj.float_value
        elif v_type == "bool_value":
            v = v_obj.bool_value
        elif v_type == "null_value":
            v = None
        elif v_type == "tuple_value":
            v = tuple(v_obj.tuple_value.string_values)
        d[k] = v
    return d
