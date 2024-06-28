import pathlib
import platform

import pytest


@pytest.mark.wandb_core_only
@pytest.mark.depends(
    deps=[
        "jax==0.4.30",
        "jaxlib==0.4.30",
        "numpy",
    ]
)
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Windows VMs in CI are slow and expensive.",
)
def test_log_bfloat16(user, relay_server, execute_script):
    with relay_server() as relay:
        return_code = execute_script(
            pathlib.Path(__file__).parent / "01-log-bfloat16.py"
        )

    assert return_code == 0

    history = relay.context.history
    assert len(history) == 1

    run_id = history.loc[0]["__run_id"]
    config = relay.context.config
    # jax import registered in telemetry (see wandb_telemetry.proto)
    assert 12 in config[run_id]["_wandb"]["value"]["t"]["1"]

    summary = relay.context.summary.loc[0].to_dict()
    assert summary["m1"] == 1
    assert summary["m2"] == 2
    assert summary["m3"] == [3, 4]
