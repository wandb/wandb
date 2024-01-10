"""type_info library.

Routines related to passing type information for input and output type info used for launch primarily.
"""

import json

from wandb.proto import wandb_internal_pb2 as pb2
from wandb.sdk.data_types._dtypes import TypeRegistry


def make_type_info(config_response, summary_response) -> None:
    type_info =pb2.TypeInfoRequest()
    # TODO: should have this in a protolib probably
    final_summary = {
        item.key: json.loads(item.value_json)
        for item in summary_response.item
        if not item.key.startswith("_")
    }
    output_types = TypeRegistry.type_of(final_summary).to_json()
    # TODO: make this cleaner ofcourse
    type_dict = output_types["params"]["type_map"]
    for k, v in type_dict.items():
        type_info.output_json_types[k] = json.dumps(v)
    return type_info
