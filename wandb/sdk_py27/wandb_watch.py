#
"""
watch.
"""

import logging
import os

import wandb

from .lib import telemetry
from .lib.ipython import _get_python_type

logger = logging.getLogger("wandb")

_global_watch_idx = 0


def watch(models, criterion=None, log="gradients", log_freq=1000, idx=None):
    """
    Hooks into the torch model to collect gradients and the topology.  Should be extended
    to accept arbitrary ML models.

    Args:
        models: (torch.Module) The model to hook, can be a tuple
        criterion: (torch.F) An optional loss value being optimized
        log: (str) One of "gradients", "parameters", "all", or None
        log_freq: (int) log gradients and parameters every N batches
        idx: (int) an index to be used when calling wandb.watch on multiple models

    Returns:
        `wandb.Graph` The graph object that will populate after the first backward pass
    """
    global _global_watch_idx

    with telemetry.context() as tel:
        tel.feature.watch = True

    logger.info("Watching")
    # TODO: temporary override for huggingface remove after: https://github.com/huggingface/transformers/pull/4220
    if os.getenv("WANDB_WATCH") == "false":
        return

    if wandb.run is None:
        raise ValueError("You must call `wandb.init` before calling watch")

    in_jupyter = _get_python_type() != "python"

    log_parameters = False
    log_gradients = True
    if log == "all":
        log_parameters = True
    elif log == "parameters":
        log_parameters = True
        log_gradients = False
    elif log is None:
        log_gradients = False

    if not isinstance(models, (tuple, list)):
        models = (models,)

    torch = wandb.util.get_module(
        "torch", required="wandb.watch only works with pytorch, couldn't import torch."
    )

    for model in models:
        if not isinstance(model, torch.nn.Module):
            raise ValueError(
                "Expected a pytorch model (torch.nn.Module). Received "
                + str(type(model))
            )

    graphs = []
    prefix = ""
    if idx is None:
        idx = _global_watch_idx
    for local_idx, model in enumerate(models):
        global_idx = idx + local_idx
        _global_watch_idx += 1
        if global_idx > 0:
            # TODO: this makes ugly chart names like gradients/graph_1conv1d.bias
            prefix = "graph_%i" % global_idx

        wandb.run.history.torch.add_log_hooks_to_pytorch_module(
            model,
            log_parameters=log_parameters,
            log_gradients=log_gradients,
            prefix=prefix,
            log_freq=log_freq,
            jupyter_run=wandb.run if in_jupyter else None,
        )

        graph = wandb.wandb_torch.TorchGraph.hook_torch(
            model, criterion, graph_idx=global_idx
        )
        graphs.append(graph)
        # NOTE: the graph is set in run.summary by hook_torch on the backward pass
    return graphs


def unwatch(models=None):
    """Remove pytorch gradient and parameter hooks.

    Args:
        models: (list) Optional list of pytorch models that have had watch called on them
    """
    if models:
        if not isinstance(models, (tuple, list)):
            models = (models,)
        for model in models:
            if not hasattr(model, "_wandb_hook_names"):
                wandb.termwarn("%s model has not been watched" % model)
            else:
                for name in model._wandb_hook_names:
                    wandb.run.history.torch.unhook(name)
    else:
        wandb.run.history.torch.unhook_all()
