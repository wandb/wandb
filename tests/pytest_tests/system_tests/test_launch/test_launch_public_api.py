import pytest
import wandb
import wandb.apis.public
import wandb.util
from wandb import Api
from wandb.sdk.internal.internal_api import UnsupportedError


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


def test_run_queue_create(user):
    rq = wandb.apis.public.RunQueue().create(
        name="test-queue",
        entity=user,
        type="local-container",
    )
    try:
        assert rq.name == "test-queue"
        assert rq.access == "PROJECT"
        assert rq.type == "local-container"
    finally:
        rq.delete()
