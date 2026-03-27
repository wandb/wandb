import json
from unittest import mock

import pytest
import wandb
from wandb.apis.public import runs
from wandb.apis.public.runs import Run


@pytest.fixture(autouse=True)
def patch_server_features(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent unit tests from attempting to contact the real server."""
    monkeypatch.setattr(
        runs,
        "_server_provides_project_id_for_run",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        runs,
        "_server_provides_internal_id_for_project",
        lambda *args, **kwargs: False,
    )


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("config", '{"test": "test"}', {"test": "test"}),
        ("summaryMetrics", '{"test": "test"}', {"test": "test"}),
        ("systemMetrics", '{"test": "test"}', {"test": "test"}),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_string_attrs(field, value, expected):
    run = wandb.apis.public.Run(
        client=wandb.Api().client,
        entity="test",
        project="test",
        run_id="test",
        attrs={field: value},
    )
    assert getattr(run, field) == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("config", {"test": "test"}),
        ("summaryMetrics", {"test": "test"}),
        ("systemMetrics", {"test": "test"}),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary_attrs_already_parsed(field, value):
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        run = wandb.apis.public.Run(
            client=wandb.Api().client,
            entity="test",
            project="test",
            run_id="test",
            attrs={field: value},
        )
        assert getattr(run, field) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("config", 1),
        ("summaryMetrics", 1),
        ("systemMetrics", 1),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary__throws_type_error(field, value):
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        with pytest.raises(wandb.errors.CommError):
            wandb.apis.public.Run(
                client=wandb.Api().client,
                entity="test",
                project="test",
                run_id="test",
                attrs={
                    field: value,
                },
            )


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("config", '{"test": "test\ttest"}', {"test": "test\ttest"}),
        ("summaryMetrics", '{"test": "test\ttest"}', {"test": "test\ttest"}),
        ("systemMetrics", '{"test": "test\ttest"}', {"test": "test\ttest"}),
    ],
    ids=["config", "summaryMetrics", "systemMetrics"],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_control_characters(field, value, expected):
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        run = wandb.apis.public.Run(
            client=wandb.Api().client,
            entity="test",
            project="test",
            run_id="test",
            attrs={field: value},
        )
        assert getattr(run, field) == expected


def _make_lightweight_attrs():
    """Attrs matching LIGHTWEIGHT_RUN_FRAGMENT (no config/summary/system)."""
    return {
        "id": "abc123storeid",
        "tags": [],
        "name": "run-abc123",
        "displayName": "happy-fox-42",
        "sweepName": None,
        "state": "finished",
        "group": None,
        "jobType": None,
        "commit": None,
        "readOnly": False,
        "createdAt": "2026-03-24T01:00:00Z",
        "heartbeatAt": "2026-03-24T02:00:00Z",
        "description": "",
        "notes": "",
        "historyLineCount": 100,
        "user": {"name": "testuser", "username": "testuser"},
    }


def _make_full_response(lightweight_attrs):
    """Server response for a single-run query with RUN_FRAGMENT."""
    return {
        "project": {
            "run": {
                **lightweight_attrs,
                "config": json.dumps(
                    {
                        "learning_rate": {"value": 0.001},
                        "batch_size": {"value": 32},
                        "_wandb": {"value": {"t": {"1": [1, 2, 3]}}},
                    }
                ),
                "systemMetrics": "{}",
                "summaryMetrics": '{"loss": 0.5}',
                "historyKeys": "{}",
            }
        }
    }


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_lazy_run_config_triggers_full_load():
    """run.config on a lazy run should trigger load_full_data and return config."""
    client = mock.MagicMock()
    lightweight = _make_lightweight_attrs()
    client.execute.return_value = _make_full_response(lightweight)

    run = Run(
        client=client,
        entity="test-entity",
        project="test-project",
        run_id="run-abc123",
        attrs=dict(lightweight),
        lazy=True,
    )

    assert run._lazy is True
    assert run._full_data_loaded is False
    assert "config" not in run._attrs

    config = run.config

    assert run._full_data_loaded is True
    assert config == {"learning_rate": 0.001, "batch_size": 32}
    assert "_wandb" not in config


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_lazy_run_user_accessible_without_full_load():
    """run.user should work on lazy runs without triggering a full data load."""
    client = mock.MagicMock()
    lightweight = _make_lightweight_attrs()

    run = Run(
        client=client,
        entity="test-entity",
        project="test-project",
        run_id="run-abc123",
        attrs=dict(lightweight),
        lazy=True,
    )

    assert run._full_data_loaded is False
    user = run.user
    assert user.name == "testuser"
    assert run._full_data_loaded is False
