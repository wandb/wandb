from __future__ import annotations

import cwsandbox
import wandb.sandbox as wandb_sandbox

_DISCOVERY_EXCEPTION_NAMES = {
    "DiscoveryError",
    "RunwayNotFoundError",
    "TowerNotFoundError",
}


def test_sandbox_wrapper_reexports_cwsandbox_exception_classes() -> None:
    expected_exception_names = {
        name for name in cwsandbox.__all__ if name.endswith("Error")
    } - _DISCOVERY_EXCEPTION_NAMES

    assert expected_exception_names <= set(wandb_sandbox.__all__)

    assert _DISCOVERY_EXCEPTION_NAMES.isdisjoint(set(wandb_sandbox.__all__))

    for name in expected_exception_names:
        assert getattr(wandb_sandbox, name) is getattr(cwsandbox, name)
