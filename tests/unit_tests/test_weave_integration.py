from unittest import mock

import pytest
import wandb.integration.weave
from wandb.sdk import wandb_setup


@pytest.fixture
def mock_singleton(monkeypatch):
    m = mock.Mock()
    monkeypatch.setattr(wandb_setup, "singleton", lambda: m)
    return m


def test_active_run_path__returns_path(mock_singleton):
    mock_singleton.most_recent_active_run = mock.Mock(
        entity="test_entity",
        project="test_project",
        id="test_id",
    )

    path = wandb.integration.weave.active_run_path()

    assert path == wandb.integration.weave.RunPath(
        entity="test_entity",
        project="test_project",
        run_id="test_id",
    )


def test_active_run_path__no_run(mock_singleton):
    mock_singleton.most_recent_active_run = None

    path = wandb.integration.weave.active_run_path()

    assert path is None


@pytest.mark.parametrize(
    "entity,project,run_id",
    (
        ("", "project", "id"),
        ("entity", "", "id"),
        ("", "", "id"),
        ("entity", "project", ""),
        ("", "project", ""),
        ("entity", "", ""),
        ("", "", ""),
    ),
)
def test_active_run_path__empty_attr(mock_singleton, entity, project, run_id):
    mock_singleton.most_recent_active_run = mock.Mock(
        entity=entity,
        project=project,
        id=run_id,
    )

    path = wandb.integration.weave.active_run_path()

    assert path is None
