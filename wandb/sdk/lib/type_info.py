"""type_info library.

Routines related to passing type information for input and output type info used for launch primarily.
"""

import json

from wandb.proto import wandb_internal_pb2 as pb2
from wandb.sdk.data_types._dtypes import TypeRegistry


def make_type_info(inputs, ouputs) -> pb2.TypesInfoRequest:
    type_info = pb2.TypesInfoRequest()
    # TODO: should have this in a protolib probably
    filter_outputs = {
        item.key: json.loads(item.value_json)
        for item in ouputs.item
        if not item.key.startswith("_")
    }
    output_types = TypeRegistry.type_of(filter_outputs).to_json()
    # TODO: make this cleaner ofcourse
    type_dict = output_types["params"]["type_map"]
    for k, v in type_dict.items():
        type_info.output_json_types[k] = json.dumps(v)

    # filter_inputs = {
    #     item.key: json.loads(item.value_json)
    #     for item in inputs.item
    #     if not item.key.startswith("_")
    # }
    # input_types = TypeRegistry.type_of(filter_inputs).to_json()
    # type_dict = input_types["params"]["type_map"]
    # for k, v in type_dict.items():
    #     type_info.input_json_types[k] = json.dumps(v)
    return type_info
