"""
pytorch profiler
"""
import os

import wandb
from wandb.errors import Error, UsageError

PYTORCH_MODULE = "torch"
PYTORCH_PROFILER_MODULE = "torch.profiler"


def trace():
    torch = wandb.util.get_module(PYTORCH_MODULE, required=True)
    torch_profiler = wandb.util.get_module(PYTORCH_PROFILER_MODULE, required=True)
    version = tuple(map(lambda x: int(x), torch.__version__.split(".")))

    if version < (1, 9, 0):
        raise Error(
            f"torch version must be at least 1.9 in order to use the PyTorch Profiler API.\
            \nVersion of torch currently installed: {torch.__version__}"
        )

    try:
        logdir = os.path.join(wandb.run.dir, "pytorch_traces")
        os.mkdir(logdir)
    except AttributeError:
        raise UsageError(
            "Please call wandb.init() before wandb.profiler.trace()"
        ) from None

    return torch_profiler.tensorboard_trace_handler(logdir)
