import asyncio
from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.agent2.jobset import JobSet, JobSetSpec, create_jobset


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


def test_create_jobset(mocker):
    api = MagicMock()

    get_jobset_response = {
        "metadata": {
            "@id": "test-id",
            "@name": "test-queue",
            "@target_resource": "test-resource",
        },
        "jobs": [],
    }

    api.get_jobset_by_spec = MagicMock(return_value=get_jobset_response)
    spec = JobSetSpec("test-queue", "test-entity", None)
    js = create_jobset(spec, api, "test-agent-id", MagicMock())
    assert isinstance(js, JobSet)


def test_jobset_init():
    api = MagicMock()
    get_jobset_response = {
        "metadata": {
            "@id": "test-id",
            "@name": "test-queue",
            "@target_resource": "test-resource",
        },
        "jobs": [],
    }
    js = JobSet(api, get_jobset_response, "test-agent-id", MagicMock())
    assert js.id == "test-id"
    assert js.name == "test-queue"
    assert js._metadata == get_jobset_response["metadata"]


@pytest.mark.asyncio
async def test_jobset_loop_start_stop(event_loop, mocker):
    async_mock = AsyncMock()
    mocker.patch("asyncio.sleep", async_mock)

    api = MagicMock()
    get_jobset_response = {
        "metadata": {
            "@id": "test-id",
            "@name": "test-queue",
            "@target_resource": "test-resource",
        },
        "jobs": [],
    }
    js = JobSet(api, get_jobset_response, "test-agent-id", MagicMock())
    js.start_sync_loop(event_loop)

    with pytest.raises(RuntimeError):
        await js.start_sync_loop(event_loop)

    js.stop_sync_loop()

    await js.wait_for_done


@pytest.mark.asyncio
async def test_jobset_ops(event_loop, mocker):
    mocker.patch("asyncio.sleep", AsyncMock())

    api = MagicMock()
    api.lease_jobset_item = AsyncMock(return_value=True)
    api.ack_jobset_item = AsyncMock(return_value=True)
    api.fail_run_queue_item = AsyncMock(return_value=True)
    api.get_jobset_diff_by_id = AsyncMock(
        return_value={
            "version": 1,
            "complete": True,
            "metadata": {},
            "upsert_jobs": [],
            "remove_jobs": [],
        }
    )

    get_jobset_response = {
        "metadata": {
            "@id": "test-id",
            "@name": "test-queue",
            "@target_resource": "test-resource",
        },
        "jobs": [],
    }
    js = JobSet(api, get_jobset_response, "test-agent-id", MagicMock())
    js.start_sync_loop(event_loop)

    tasks = asyncio.gather(
        js.lease_job("test-job-1"),
        js.ack_job("test-job-1", "test-run-1"),
        js.fail_job("test-job-1", "test message", "test stage"),
    )

    await tasks

    js.stop_sync_loop()
    await js.wait_for_done
