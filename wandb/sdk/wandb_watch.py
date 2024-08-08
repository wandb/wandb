"""watch."""

import logging
from typing import Optional

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal  # type: ignore

import wandb

from .lib import telemetry

logger = logging.getLogger("wandb")

_global_watch_idx = 0


def watch(
    models,
    criterion=None,
    log: Optional[Literal["gradients", "parameters", "all"]] = "gradients",
    log_freq: int = 1000,
    idx: Optional[int] = None,
    log_graph: bool = False,
):
    """Hook into the torch model to collect gradients and the topology.

    Should be extended to accept arbitrary ML models.

    Args:
        models: (torch.Module) The model to hook, can be a tuple
        criterion: (torch.F) An optional loss value being optimized
        log: (str) One of "gradients", "parameters", "all", or None
        log_freq: (int) log gradients and parameters every N batches
        idx: (int) an index to be used when calling wandb.watch on multiple models
        log_graph: (boolean) log graph topology

    Returns:
        `wandb.Graph`: The graph object that will populate after the first backward pass

    Raises:
        ValueError: If called before `wandb.init` or if any of models is not a torch.nn.Module.
    """
    global _global_watch_idx

    with telemetry.context() as tel:
        tel.feature.watch = True

    logger.info("Watching")

    if wandb.run is None:
        raise ValueError("You must call `wandb.init` before calling watch")

    if log not in {"gradients", "parameters", "all", None}:
        raise ValueError("log must be one of 'gradients', 'parameters', 'all', or None")

    log_parameters = log in {"parameters", "all"}
    log_gradients = log in {"gradients", "all"}

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

        if log_parameters:
            wandb.run._torch.add_log_parameters_hook(
                model,
                prefix=prefix,
                log_freq=log_freq,
            )

        if log_gradients:
            wandb.run._torch.add_log_gradients_hook(
                model,
                prefix=prefix,
                log_freq=log_freq,
            )

        if log_graph:
            graph = wandb.run._torch.hook_torch(model, criterion, graph_idx=global_idx)
            graphs.append(graph)
            # NOTE: the graph is set in run.summary by hook_torch on the backward pass
    return graphs


def unwatch(models=None):
    """Remove pytorch model topology, gradient and parameter hooks.

    Args:
        models: (list) Optional list of pytorch models that have had watch called on them
    """
    if models:
        if not isinstance(models, (tuple, list)):
            models = (models,)
        for model in models:
            if not hasattr(model, "_wandb_hook_names"):
                wandb.termwarn("{} model has not been watched".format(model))
            else:
                for name in model._wandb_hook_names:
                    wandb.run._torch.unhook(name)
                delattr(model, "_wandb_hook_names")
                # TODO: we should also remove recursively model._wandb_watch_called

    else:
        wandb.run._torch.unhook_all()
