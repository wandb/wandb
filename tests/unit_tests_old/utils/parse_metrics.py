"""Parse metrics json encoded protobuf list.

Decode json encoded form of a List of MetricRecord protobufs

Definition of record:
    https://github.com/wandb/wandb/blob/master/wandb/proto/wandb_internal.proto

Encoder function:
    https://github.com/wandb/wandb/blob/master/wandb/sdk/lib/proto_util.py

Example:
    {'loss': 'global_step', 'acc': 'global_step', 'v1': 'other_step'}

"""

_SAMPLE_METRIC_LIST = [
    {"1": "global_step", "6": [2]},
    {"1": "loss", "5": 1, "6": [1], "7": [1, 2, 3, 4], "8": 2},
    {"1": "acc", "5": 1, "6": [1], "7": [1, 2, 3, 4], "8": 2},
    {"1": "other_step", "6": [2]},
    {"1": "v1", "5": 4, "6": [1], "7": [1, 2, 3, 4], "8": 2},
]


def get_step_metric_dict(ml):
    """Get mapping from metric to preferred x-axis."""
    nl = [m["1"] for m in ml]
    md = {m["1"]: nl[m["5"] - 1] for m in ml if m.get("5")}
    return md


if __name__ == "__main__":
    print(get_step_metric_dict(_SAMPLE_METRIC_LIST))
