import pytest
import wandb
import wandb.apis.public
import wandb.util
from wandb import Api
from wandb.sdk.internal.internal_api import UnsupportedError

SWEEP_CONFIGURATION = {
    "method": "random",
    "name": "sweep",
    "metric": {"goal": "maximize", "name": "val_acc"},
    "parameters": {
        "batch_size": {"values": [16, 32, 64]},
        "epochs": {"values": [5, 10, 15]},
        "lr": {"max": 0.1, "min": 0.0001},
    },
}


def test_create_run_queue_template_variables_not_supported(runner, user, monkeypatch):
    queue_name = "tvqueue"
    queue_config = {"e": ["{{var1}}"]}
    queue_template_variables = {
        "var1": {"schema": {"type": "string", "enum": ["a", "b"]}}
    }

    def patched_push_to_run_queue_introspection(*args, **kwargs):
        args[0].server_supports_template_variables = False, False
        return False, False

    monkeypatch.setattr(
        wandb.sdk.internal.internal_api.Api,
        "push_to_run_queue_introspection",
        patched_push_to_run_queue_introspection,
    )
    with runner.isolated_filesystem():
        api = Api(api_key=user)
        with pytest.raises(UnsupportedError):
            api.create_run_queue(
                entity=user,
                name=queue_name,
                type="local-container",
                config=queue_config,
                template_variables=queue_template_variables,
            )


def test_run_queue(user):
    api = Api()
    queue = api.create_run_queue(
        name="test-queue",
        entity=user,
        type="local-container",
    )
    try:
        assert queue.name == "test-queue"
        assert queue.access == "PROJECT"
        assert queue.type == "local-container"
    finally:
        queue.delete()


def test_from_path(user):
    api = Api()

    project = "my-first-sweep"
    sweep_id = wandb.sweep(sweep=SWEEP_CONFIGURATION, project=project)

    sweep = api.from_path(f"{user}/{project}/sweeps/{sweep_id}")
    assert isinstance(sweep, wandb.apis.public.Sweep)


def test_sweep(user):
    api = Api()

    project = "my-first-sweep"
    sweep_id = wandb.sweep(sweep=SWEEP_CONFIGURATION, project=project)

    sweep = api.sweep(f"{user}/{project}/{sweep_id}")

    assert sweep.entity == user
    assert sweep.url.endswith(f"{user}/{project}/sweeps/{sweep_id}")
    assert sweep.state == "PENDING"
    assert str(sweep) == f"<Sweep {user}/{project}/{sweep_id} (PENDING)>"


def test_to_html(user):
    project = "my-first-sweep"
    sweep_id = wandb.sweep(sweep=SWEEP_CONFIGURATION, project=project)

    api = Api()
    sweep = api.from_path(f"{user}/{project}/sweeps/{sweep_id}")
    assert f"{user}/{project}/sweeps/{sweep_id}?jupyter=true" in sweep.to_html()
