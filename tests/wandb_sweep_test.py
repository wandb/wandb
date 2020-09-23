"""Sweep tests"""
import wandb


def test_create_sweep(live_mock_server, test_settings):
    live_mock_server.set_ctx({"resume": True})
    sweep_config = {
        "name": "My Sweep",
        "method": "grid",
        "parameters": {
            "parameter1": {
                "values": [1, 2, 3]
            }
        }
    }
    sweep_id = wandb.sweep(sweep_config)
    assert sweep_id == 'test'
