import json

import pytest
import wandb
import wandb.apis.public
from wandb import Api
from wandb.errors import UnsupportedError

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


def test_upsert_run_queue(user):
    """Test creating a run queue with upsert.

    The `upsert_run_queue` method introspects gorilla to see if the
    `upsertRunQueue` mutation is supported. If it is not, this test is skipped.
    """
    api = Api()
    try:
        queue = api.upsert_run_queue(
            entity=user,
            name="test-queue",
            resource_type="local-container",
            resource_config={"cpu": "{{cpu}}"},
            template_variables={
                "cpu": {
                    "schema": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 4,
                    },
                }
            },
            external_links={"google": "https://google.com"},
        )
    except UnsupportedError:
        return pytest.skip("upsertRunQueue not supported on server version.")
    try:
        assert queue.name == "test-queue"
        assert queue.access == "PROJECT"
        assert queue.type == "local-container"
        assert queue.default_resource_config == {
            "resource_args": {"local-container": {"cpu": "{{cpu}}"}}
        }
        assert queue.template_variables == [
            {
                "name": "cpu",
                "schema": json.dumps(
                    {"type": "integer", "minimum": 1, "maximum": 4},
                    separators=(",", ":"),
                ),
            }
        ]
        assert queue.external_links == {
            "links": [
                {
                    "label": "google",
                    "url": "https://google.com",
                }
            ]
        }

        # Upsert the same queue with different values and check that the
        # the fields are updated.
        queue = api.upsert_run_queue(
            entity=user,
            name="test-queue",
            resource_type="local-container",
            resource_config={"cpu": 2},
            external_links={"yahoo": "https://yahoo.com"},
            template_variables={},
        )
        assert queue.default_resource_config == {
            "resource_args": {
                "local-container": {
                    "cpu": 2,
                },
            }
        }
        assert queue.template_variables == []
        assert queue.external_links == {
            "links": [
                {
                    "label": "yahoo",
                    "url": "https://yahoo.com",
                }
            ]
        }
    finally:
        queue.delete()


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
