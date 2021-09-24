"""
pytorch profiler
"""
import os

import wandb
from wandb.errors import UsageError

PYTORCH_PROFILER_MODULE = "torch.profiler"


def trace():
    torch_profiler = wandb.util.get_module(PYTORCH_PROFILER_MODULE, required=True)
    try:
        logdir = os.path.join(wandb.run.dir, "pytorch_traces")
        os.mkdir(logdir)
    except AttributeError:
        raise UsageError(
            "Please call wandb.init() before wandb.profiler.trace()"
        ) from None

    return torch_profiler.tensorboard_trace_handler(
        logdir, worker_name=None, use_gzip=False
    )
