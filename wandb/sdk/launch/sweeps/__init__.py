import logging
from typing import Callable, Dict

from .daimyo import Daimyo


log = logging.getLogger(__name__)


def _import_sweep_daimyo() -> Daimyo:
    from .sweep_daimyo import SweepDaimyo

    # TODO: Load dependencies for SweepDaimyo
    # pip install wandb[sweeps]
    return SweepDaimyo


def _import_tune_daimyo() -> Daimyo:
    from .tune_daimyo import TuneDaimyo

    # TODO: Load dependencies for TuneDaimyo
    # pip install ray[tune]
    return TuneDaimyo


_WANDB_DAIMYOS: Dict[str, Callable] = {
    "tune": _import_tune_daimyo,
    "sweep": _import_sweep_daimyo,
}


def load_daimyo(daimyo_name: str, *args, **kwargs) -> Daimyo:

    daimyo_name = daimyo_name.lower()
    if daimyo_name not in _WANDB_DAIMYOS:
        raise ValueError(
            f"The `daimyo_name` argument must be one of "
            f"{list(_WANDB_DAIMYOS.keys())}, got: {daimyo_name}"
        )

    log.warn(f"Loading dependencies for Daimyo of type: {daimyo_name}")
    import_func = _WANDB_DAIMYOS[daimyo_name]
    return import_func()(*args, **kwargs)


__all__ = [
    "load_daimyo",
]
