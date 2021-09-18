"""
pytorch profiler
"""
import wandb

PYTORCH_PROFILER_MODULE = "torch.profiler"


def trace():
    torch_profiler = wandb.util.get_module(PYTORCH_PROFILER_MODULE)
    try:
        logdir = wandb.run.dir
    except AttributeError:
        raise Exception(
            "Please call wandb.init() before wandb.profiler.trace()"
        ) from None

    return torch_profiler.tensorboard_trace_handler(
        logdir, worker_name=None, use_gzip=False
    )
