from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.agent2.controllers.k8s import KubernetesManager


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@pytest.fixture
def k8s_container_manager(controller_config, jobset):
    return KubernetesManager(
        controller_config, jobset, MagicMock(), MagicMock(), AsyncMock, 1
    )


@pytest.mark.parametrize(
    "resource_args, expected",
    [
        ({}, None),
        ({"kubernetes": {}}, {"_wandb-jobset": "test-entity/test"}),
        (
            {"kubernetes": {"metadata": {"not-labels": True}}},
            {"_wandb-jobset": "test-entity/test"},
        ),
        (
            {"kubernetes": {"metadata": {"labels": {"BLAH": "test-label"}}}},
            {"_wandb-jobset": "test-entity/test", "BLAH": "test-label"},
        ),
    ],
)
def test_label_job(resource_args, expected, k8s_container_manager):
    project = MagicMock()
    project.resource_args = resource_args
    k8s_container_manager.label_job(project)
    assert (
        project.resource_args.get("kubernetes", {}).get("metadata", {}).get("labels")
        == expected
    )
