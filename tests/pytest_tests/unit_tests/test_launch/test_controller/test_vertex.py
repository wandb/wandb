

from unittest.mock import MagicMock
from wandb.sdk.launch.agent2.controllers.vertex import VertexManager
from wandb.sdk.launch.agent2.jobset import JobSetSpec
from wandb.sdk.launch._project_spec import LaunchProject
import pytest


@pytest.mark.asyncio
async def test_label_job(monkeypatch):
    monkeypatch.setattr("wandb.sdk.launch.agent2.controllers.vertex.StandardQueueDriver", MagicMock())
    jobset_spec = JobSetSpec(
        name="test-jobsetspec",
        entity_name="test-entity",
        project_name="test-project",
    )
    config = {
        "jobset_spec": jobset_spec
    }
    manager = VertexManager(config=config, jobset=MagicMock(), logger=MagicMock(), legacy=MagicMock(), max_concurrency=1)
    project_spec = {
        "resource_args": {"vertex": {"labels": {"test-label": "test-value"}}},
        "entity": "test-entity",
        "project": "test-project",
    }
    project = LaunchProject.from_spec(project_spec, MagicMock())

    await manager.label_job(project)
    assert project.resource_args == {
        "vertex": {
            "labels": {
                "_wandb-jobset": "test-entity/test-jobsetspec",
                "test-label": "test-value",
            }
        }
    }