import queue
import time
from typing import TYPE_CHECKING, Iterable, Mapping
from unittest.mock import Mock

import pytest
from wandb.filesync.step_prepare import ResponsePrepare, StepPrepare

if TYPE_CHECKING:
    from wandb.sdk.internal.internal_api import (
        CreateArtifactFileSpecInput,
        CreateArtifactFilesResponseFile,
    )


def simple_file_spec(name: str) -> "CreateArtifactFileSpecInput":
    return {
        "name": name,
        "artifactID": "some-artifact-id",
        "md5": "some-md5",
    }


def mock_create_artifact_files_result(
    names: Iterable[str],
) -> Mapping[str, "CreateArtifactFilesResponseFile"]:
    return {
        name: {
            "id": f"file-id-{name}",
            "name": name,
            "displayName": f"file-displayname-{name}",
            "uploadUrl": f"http://wandb-test/upload-url-{name}",
            "uploadHeaders": ["x-my-header-key:my-header-val"],
            "artifact": {
                "id": f"artifact-id-{name}",
            },
        }
        for name in names
    }


def test_smoke():
    caf_result = mock_create_artifact_files_result(["foo"])
    api = Mock(create_artifact_files=Mock(return_value=caf_result))

    step_prepare = StepPrepare(
        api=api, batch_time=1e-12, inter_event_time=1e-12, max_batch_size=1
    )
    step_prepare.start()

    res = step_prepare.prepare(simple_file_spec(name="foo"))

    assert res == ResponsePrepare(
        upload_url=caf_result["foo"]["uploadUrl"],
        upload_headers=caf_result["foo"]["uploadHeaders"],
        birth_artifact_id=caf_result["foo"]["artifact"]["id"],
    )


def test_respects_max_batch_size():
    caf_result = mock_create_artifact_files_result(["a", "b", "c"])
    api = Mock(create_artifact_files=Mock(return_value=caf_result))

    step_prepare = StepPrepare(
        api=api, batch_time=0.1, inter_event_time=0.1, max_batch_size=2
    )
    step_prepare.start()

    queues = []
    for name in ["a", "b", "c"]:
        queues.append(step_prepare.prepare_async(simple_file_spec(name=name)))

    [q.get() for q in queues]

    assert api.create_artifact_files.call_count == 2
    assert [f["name"] for f in api.create_artifact_files.call_args_list[0][0][0]] == [
        "a",
        "b",
    ]
    assert [f["name"] for f in api.create_artifact_files.call_args_list[1][0][0]] == [
        "c"
    ]


def test_respects_max_batch_time():
    caf_result = mock_create_artifact_files_result(["a", "b"])
    api = Mock(create_artifact_files=Mock(return_value=caf_result))

    step_prepare = StepPrepare(
        api=api, batch_time=0.2, inter_event_time=100, max_batch_size=100
    )
    step_prepare.start()

    q = step_prepare.prepare_async(simple_file_spec(name="a"))

    with pytest.raises(queue.Empty):
        q.get(block=False)

    # I hate having sleeps in tests, but I can't think of a good way to mock out
    # the time mechanism in StepPrepare: it doesn't sleep(), it calls
    # `Queue.get(timeout=...)`, which doesn't provide a way to mock the sleep.
    # We could mock out the Queue, but... that seems fiddly.
    time.sleep(0.3)

    q.get(block=False)

    api.create_artifact_files.assert_called_once()


def test_respects_inter_event_time():
    caf_result = mock_create_artifact_files_result(["a", "b", "c", "d"])
    api = Mock(create_artifact_files=Mock(return_value=caf_result))

    step_prepare = StepPrepare(
        api=api, batch_time=100, inter_event_time=0.2, max_batch_size=100
    )
    step_prepare.start()

    queues = []
    # t=0
    queues.append(step_prepare.prepare_async(simple_file_spec(name="a")))
    time.sleep(0.13)  # as above, I hate having sleeps in tests, but...
    # t=0.13
    queues.append(step_prepare.prepare_async(simple_file_spec(name="b")))
    time.sleep(0.13)
    # t=0.26
    queues.append(step_prepare.prepare_async(simple_file_spec(name="c")))

    time.sleep(0.3)  # exceeds inter_event_time; batch should fire

    for q in queues:
        q.get()

    api.create_artifact_files.assert_called_once()
    assert [f["name"] for f in api.create_artifact_files.call_args[0][0]] == [
        "a",
        "b",
        "c",
    ]
