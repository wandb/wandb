from __future__ import annotations

from typing import get_args, get_type_hints
from unittest.mock import patch

import pytest
import wandb


def test_controller_sweep_config_annotation_includes_none():
    sweeps = pytest.importorskip("sweeps")
    from wandb.wandb_controller import _WandbController

    hints = get_type_hints(_WandbController.sweep_config.fget)
    assert type(None) in get_args(hints["return"])
    assert dict in get_args(hints["return"])
    assert sweeps.SweepConfig in get_args(hints["return"])

    with patch("wandb.Api"):
        controller = wandb.controller()
        assert controller.sweep_config is None
        assert controller._stopping() == []
        controller.configure_search("random")
        controller.configure_metric("loss")
        assert controller.sweep_config is None
