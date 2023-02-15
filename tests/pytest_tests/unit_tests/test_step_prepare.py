import asyncio
import concurrent.futures
import threading
import time
from typing import TYPE_CHECKING, Iterable, Mapping
from unittest.mock import Mock

import pytest
from wandb.filesync.step_prepare import ResponsePrepare, StepPrepare

if TYPE_CHECKING:
    import sys

    from wandb.sdk.internal.internal_api import (
        CreateArtifactFileSpecInput,
        CreateArtifactFilesResponseFile,
    )

    if sys.version_info >= (3, 8):
        from typing import Protocol
    else:
        from typing_extensions import Protocol

    class PrepareFixture(Protocol):
        def __call__(
            self,
            step_prepare: StepPrepare,
            file_spec: "CreateArtifactFileSpecInput",
        ) -> "concurrent.futures.Future[ResponsePrepare]":
            pass


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


def _bg_prepare_sync(
    step_prepare: StepPrepare, *args, **kwargs
) -> "concurrent.futures.Future[ResponsePrepare]":
    """Starts prepare_sync running in the background.

    Don't call this directly; use the `prepare` fixture instead, to ensure that
    whatever logic you're testing works with both sync and async impls.

    If you're writing a test that only cares about the sync impl, you should
    probably just call `step_prepare.prepare_sync` directly.
    """

    future = concurrent.futures.Future()

    def prepare_and_resolve():
        future.set_result(step_prepare.prepare_sync(*args, **kwargs))

    threading.Thread(
        name="prepare_and_resolve",
        target=prepare_and_resolve,
        daemon=True,
    ).start()

    return future


def _bg_prepare_async(
    step_prepare: StepPrepare, *args, **kwargs
) -> "concurrent.futures.Future[ResponsePrepare]":
    """Starts prepare_async running in the background.

    Don't call this directly; use the `prepare` fixture instead, to ensure that
    whatever logic you're testing works with both sync and async impls.

    If you're writing a test that only cares about the async impl, you should
    probably just call `step_prepare.prepare_sync` directly.
    """

    future = concurrent.futures.Future()

    async def prepare_and_resolve():
        future.set_result(await step_prepare.prepare_async(*args, **kwargs))

    threading.Thread(
        name="prepare_and_resolve",
        target=asyncio.new_event_loop().run_until_complete,
        args=[prepare_and_resolve()],
        daemon=True,
    ).start()

    return future


@pytest.fixture(params=["sync", "async"])
def prepare(request) -> "PrepareFixture":
    """Fixture to kick off prepare_sync or prepare_async in the background.

    Example usage:

        def test_smoke(prepare: "PrepareFixture"):
            step_prepare = StepPrepare(...)
            step_prepare.start()
            res = prepare(step_prepare, simple_file_spec(name="foo")).result()
            assert res.birth_artifact_id == ...
    """
    if request.param == "sync":
        return _bg_prepare_sync
    elif request.param == "async":
        return _bg_prepare_async
    else:
        raise ValueError(f"Unknown prepare mode: {request.param}")


def test_smoke(prepare: "PrepareFixture"):
    caf_result = mock_create_artifact_files_result(["foo"])
    api = Mock(create_artifact_files=Mock(return_value=caf_result))

    step_prepare = StepPrepare(
        api=api, batch_time=1e-12, inter_event_time=1e-12, max_batch_size=1
    )
    step_prepare.start()

    res = prepare(step_prepare, simple_file_spec(name="foo")).result()

    assert res == ResponsePrepare(
        upload_url=caf_result["foo"]["uploadUrl"],
        upload_headers=caf_result["foo"]["uploadHeaders"],
        birth_artifact_id=caf_result["foo"]["artifact"]["id"],
    )


def test_respects_max_batch_size(prepare: "PrepareFixture"):
    caf_result = mock_create_artifact_files_result(["a", "b", "c"])
    api = Mock(create_artifact_files=Mock(return_value=caf_result))

    step_prepare = StepPrepare(
        api=api, batch_time=0.1, inter_event_time=0.1, max_batch_size=2
    )
    step_prepare.start()

    futures = []
    for name in ["a", "b", "c"]:
        futures.append(prepare(step_prepare, simple_file_spec(name=name)))

    for future in futures:
        future.result()

    assert api.create_artifact_files.call_count == 2
    assert len(api.create_artifact_files.call_args_list[0][0][0]) == 2
    assert len(api.create_artifact_files.call_args_list[1][0][0]) == 1


def test_respects_max_batch_time(prepare: "PrepareFixture"):
    caf_result = mock_create_artifact_files_result(["a", "b"])
    api = Mock(create_artifact_files=Mock(return_value=caf_result))

    step_prepare = StepPrepare(
        api=api, batch_time=0.1, inter_event_time=100, max_batch_size=100
    )
    step_prepare.start()

    future = prepare(step_prepare, simple_file_spec(name="a"))

    with pytest.raises(concurrent.futures.TimeoutError):
        future.result(timeout=0.05)

    future.result(timeout=0.1)

    api.create_artifact_files.assert_called_once()


def test_respects_inter_event_time(prepare: "PrepareFixture"):
    caf_result = mock_create_artifact_files_result(["a", "b", "c", "d"])
    api = Mock(create_artifact_files=Mock(return_value=caf_result))

    step_prepare = StepPrepare(
        api=api, batch_time=100, inter_event_time=0.1, max_batch_size=100
    )
    step_prepare.start()

    futures = []
    # t=0
    futures.append(prepare(step_prepare, simple_file_spec(name="a")))
    time.sleep(0.07)
    # t=0.07
    futures.append(prepare(step_prepare, simple_file_spec(name="b")))
    time.sleep(0.07)
    # t=0.14
    futures.append(prepare(step_prepare, simple_file_spec(name="c")))

    api.create_artifact_files.assert_not_called()

    time.sleep(0.15)  # exceeds inter_event_time; batch should fire

    for future in futures:
        future.result(timeout=1e-12)

    api.create_artifact_files.assert_called_once()
    assert {f["name"] for f in api.create_artifact_files.call_args[0][0]} == {
        "a",
        "b",
        "c",
    }
