import tensorflow as tf
from collections import defaultdict, OrderedDict
import json


def read_tensorflow_log_file(event_file_path):
    scalars = defaultdict(OrderedDict)
    first = None
    for e in tf.train.summary_iterator(event_file_path):
        if not first:
            first = e.wall_time
        for v in e.summary.value:
            if v.simple_value:
                scalars[int(e.wall_time)][v.tag] = v.simple_value

    with open("wandb-history.jsonl", "w") as f:
        for key, value in scalars.items():
            value["_runtime"] = key - first
            value["_time"] = key
            f.write(json.dumps(value) + "\n")

    return scalars
