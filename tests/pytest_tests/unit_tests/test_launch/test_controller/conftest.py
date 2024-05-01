from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.agent2.controller import LaunchControllerConfig
from wandb.sdk.launch.agent2.jobset import JobSetSpec, create_jobset


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@pytest.fixture
def jobset_spec():
    return JobSetSpec(name="test", entity_name="test-entity", project_name="test-proj")


@pytest.fixture
def jobset(jobset_spec):
    entity = "test-entity"
    mock_api = AsyncMock()
    mock_api.get_jobset_by_spec.return_value = {
        "jobSetDiff": {
            "jobs": [
                {
                    "createdAt": "2024-04-09T16:33:45",
                    "updatedAt": None,
                    "id": "test-id",
                    "runSpec": {
                        "job": f"{entity}/test-proj/job-ktest12abc:latest",
                        "author": f"{entity}",
                        "entity": f"{entity}",
                        "project": "test-proj",
                        "resource": "local-container",
                        "overrides": {"args": [], "run_config": {}, "entry_point": []},
                        "resource_args": {"local-container": {}},
                        "_wandb_job_collection_id": "arti-id",
                    },
                    "priority": 2,
                    "state": "PENDING",
                    "associatedRunId": None,
                    "launchAgentId": None,
                }
            ],
            "metadata": {
                "@target_resource": "local-container",
                "@id": "jobset-id",
                "@name": "docker-queue-kyle",
                "@capacity": 500,
                "@max_concurrency": "auto",
                "@prioritization_mode": "V0",
            },
        }
    }
    return create_jobset(jobset_spec, MagicMock(), "test-agent", MagicMock())


@pytest.fixture
def controller_config(jobset, jobset_spec):
    return LaunchControllerConfig(
        {
            "agent_id": jobset.agent_id,
            "jobset_spec": jobset_spec,
            "jobset_metadata": jobset._metadata,
        }
    )
