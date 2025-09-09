"""watch."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Sequence

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal  # type: ignore

import wandb

from .lib import telemetry

if TYPE_CHECKING:
    import torch  # type: ignore [import-not-found]

logger = logging.getLogger("wandb")

_global_watch_idx = 0


def _watch(
    run: wandb.Run,
    models: torch.nn.Module | Sequence[torch.nn.Module],
    criterion: torch.F | None = None,
    log: Literal["gradients", "parameters", "all"] | None = "gradients",
    log_freq: int = 1000,
    idx: int | None = None,
    log_graph: bool = False,
):
    """Hooks into the given PyTorch model(s) to monitor gradients and the model's computational graph.

    This function can track parameters, gradients, or both during training. It should be
    extended to support arbitrary machine learning models in the future.

    Args:
        run (wandb.Run): The run object to log to.
        models (Union[torch.nn.Module, Sequence[torch.nn.Module]]):
            A single model or a sequence of models to be monitored.
        criterion (Optional[torch.F]):
            The loss function being optimized (optional).
        log (Optional[Literal["gradients", "parameters", "all"]]):
            Specifies whether to log "gradients", "parameters", or "all".
            Set to None to disable logging. (default="gradients")
        log_freq (int):
            Frequency (in batches) to log gradients and parameters. (default=1000)
        idx (Optional[int]):
            Index used when tracking multiple models with `wandb.watch`. (default=None)
         log_graph (bool):
            Whether to log the model's computational graph. (default=False)

    Returns:
        wandb.Graph:
            The graph object, which will be populated after the first backward pass.

    Raises:
        ValueError: If `wandb.init` has not been called.
        TypeError: If any of the models are not instances of `torch.nn.Module`.
    """
    global _global_watch_idx

    with telemetry.context() as tel:
        tel.feature.watch = True

    logger.info("Watching")

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
            raise TypeError(
                f"Expected a pytorch model (torch.nn.Module). Received {type(model)}"
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
            prefix = f"graph_{global_idx}"

        if log_parameters:
            run._torch.add_log_parameters_hook(
                model,
                prefix=prefix,
                log_freq=log_freq,
            )

        if log_gradients:
            run._torch.add_log_gradients_hook(
                model,
                prefix=prefix,
                log_freq=log_freq,
            )

        if log_graph:
            graph = run._torch.hook_torch(model, criterion, graph_idx=global_idx)
            graphs.append(graph)
            # NOTE: the graph is set in run.summary by hook_torch on the backward pass
    return graphs


def _unwatch(
    run: wandb.Run, models: torch.nn.Module | Sequence[torch.nn.Module] | None = None
) -> None:
    """Remove pytorch model topology, gradient and parameter hooks.

    Args:
        run (wandb.Run):
            The run object to log to.
        models (torch.nn.Module | Sequence[torch.nn.Module]):
            Optional list of pytorch models that have had watch called on them
    """
    if models:
        if not isinstance(models, (tuple, list)):
            models = (models,)
        for model in models:
            if not hasattr(model, "_wandb_hook_names"):
                wandb.termwarn(f"{model} model has not been watched")
            else:
                for name in model._wandb_hook_names:
                    run._torch.unhook(name)
                delattr(model, "_wandb_hook_names")
                # TODO: we should also remove recursively model._wandb_watch_called

    else:
        run._torch.unhook_all()
