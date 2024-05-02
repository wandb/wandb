from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.agent2.controllers.local_container import LocalContainerManager
from wandb.sdk.lib.hashutil import b64_to_hex_id, md5_string


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@pytest.fixture
def local_container_manager(controller_config, jobset):
    return LocalContainerManager(
        controller_config, jobset, MagicMock(), MagicMock(), AsyncMock(), 1
    )


JOBSET_LABEL = b64_to_hex_id(md5_string("test-entity/test"))


@pytest.mark.parametrize(
    "resource_args, expected",
    [
        (
            {},
            None,
        ),  # if empty don't update do nothing, queues always populate so it is a push launch job
        (
            {"local-container": {}},
            [f"_wandb-jobset={JOBSET_LABEL}"],
        ),  # if set but populated, add label
        # otherwise use existing label key and add to labels list or create a new list from string
        (
            {"local-container": {"l": ["BLAH=test-label"]}},
            [f"_wandb-jobset={JOBSET_LABEL}", "BLAH=test-label"],
        ),
        (
            {"local-container": {"l": "BLAH=test-label"}},
            [f"_wandb-jobset={JOBSET_LABEL}", "BLAH=test-label"],
        ),
        (
            {"local-container": {"label": ["BLAH=test-label"]}},
            [f"_wandb-jobset={JOBSET_LABEL}", "BLAH=test-label"],
        ),
        (
            {"local-container": {"label": "BLAH=test-label"}},
            [f"_wandb-jobset={JOBSET_LABEL}", "BLAH=test-label"],
        ),
    ],
)
def test_label_job(local_container_manager, resource_args, expected):
    mock_project = MagicMock()
    mock_project.resource_args = resource_args
    local_container_manager.label_job(mock_project)
    if expected is None:
        assert mock_project.resource_args.get("local-container") is None
    else:
        key = "label" if "label" in resource_args.get("local-container") else "l"
        for e in expected:
            assert e in mock_project.resource_args.get("local-container").get(key, [])
