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
    import flax  # type: ignore [import-not-found]
    import torch  # type: ignore [import-not-found]

    WatchableModel = (
        torch.nn.Module
        | flax.linen.Module
        | Sequence[torch.nn.Module]
        | Sequence[flax.linen.Module]
    )

logger = logging.getLogger("wandb")

_global_watch_idx = 0


def _is_flax_module(model) -> bool:
    """Check if a model is a Flax module."""
    try:
        import flax.linen as nn

        if isinstance(model, nn.Module):
            return True
    except ImportError:
        pass

    # Fallback to typename checking
    typename = wandb.util.get_full_typename(model)
    return typename.startswith("flax.linen.") or typename.startswith("flax.nn.")


def _watch(
    run: wandb.Run,
    models: WatchableModel,
    criterion: torch.F | None = None,
    log: Literal["gradients", "parameters", "all"] | None = "gradients",
    log_freq: int = 1000,
    idx: int | None = None,
    log_graph: bool = False,
):
    """Hooks into the given model(s) to monitor gradients and the model's computational graph.

    This function can track parameters, gradients, or both during training.
    Supports PyTorch and Flax models.

    Args:
        run (wandb.Run): The run object to log to.
        models (WatchableModel):
            A single model or a sequence of models to be monitored.
            Supports PyTorch (torch.nn.Module) and Flax (flax.linen.Module).
        criterion (Optional[torch.F]):
            The loss function being optimized (optional, PyTorch only).
        log (Optional[Literal["gradients", "parameters", "all"]]):
            Specifies whether to log "gradients", "parameters", or "all".
            Set to None to disable logging. (default="gradients")
        log_freq (int):
            Frequency (in batches) to log gradients and parameters. (default=1000)
        idx (Optional[int]):
            Index used when tracking multiple models with `wandb.watch`. (default=None)
         log_graph (bool):
            Whether to log the model's computational graph. (default=False, PyTorch only)

    Returns:
        wandb.Graph or None:
            The graph object for PyTorch models (populated after first backward pass).
            None for Flax models.

    Raises:
        ValueError: If `wandb.init` has not been called.
        TypeError: If any of the models are not supported types.
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

    # Detect model framework
    is_flax = any(_is_flax_module(model) for model in models)

    if is_flax:
        # Handle Flax models
        if log_graph:
            wandb.termwarn(
                "log_graph is not supported for Flax models and will be ignored."
            )

        if len(models) > 1:
            wandb.termwarn(
                "Watching multiple Flax models is not fully supported. "
                "Only the first model will be watched."
            )

        # Configure Flax watching
        model = models[0]
        run._flax.watch(model, log=log, log_freq=log_freq)

        wandb.termlog(
            "Flax model watch configured. Gradients will be automatically captured from jax.grad() and jax.value_and_grad()."
        )

        return None

    # Handle PyTorch models
    torch = wandb.util.get_module(
        "torch",
        required="Could not import torch. wandb.watch supports PyTorch and Flax models.",
    )

    for model in models:
        if not isinstance(model, torch.nn.Module):
            raise TypeError(
                f"Expected a PyTorch model (torch.nn.Module) or Flax model (flax.linen.Module). "
                f"Received {type(model)}"
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


def _unwatch(run: wandb.Run, models: WatchableModel | None = None) -> None:
    """Remove model topology, gradient and parameter hooks.

    Args:
        run (wandb.Run):
            The run object to log to.
        models (WatchableModel):
            Optional list of models that have had watch called on them.
            Can be PyTorch or Flax models.
    """
    if models:
        if not isinstance(models, (tuple, list)):
            models = (models,)

        for model in models:
            if _is_flax_module(model):
                # For Flax, we can't track individual models by hooks
                # Just unwatch everything
                run._flax.unwatch()
            else:
                # PyTorch model
                if not hasattr(model, "_wandb_hook_names"):
                    wandb.termwarn(f"{model} model has not been watched")
                else:
                    for name in model._wandb_hook_names:
                        run._torch.unhook(name)
                    delattr(model, "_wandb_hook_names")
                    # TODO: we should also remove recursively model._wandb_watch_called
    else:
        run._torch.unhook_all()
        if hasattr(run, "_flax") and run._flax is not None:
            run._flax.unwatch()
