import asyncio
import concurrent.futures
import dataclasses
import queue
import threading
from typing import TYPE_CHECKING, Iterable, Mapping, Tuple
from unittest.mock import Mock, call

import pytest
from wandb.filesync.step_prepare import (
    Request,
    RequestFinish,
    RequestPrepare,
    ResponsePrepare,
    StepPrepare,
    gather_batch,
)

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


def simple_request_prepare(name: str) -> RequestPrepare:
    return RequestPrepare(simple_file_spec(name=name), queue.Queue())


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


@dataclasses.dataclass
class MockClock:
    now: float = 0

    def __call__(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.now += duration


class MockRequestQueue(Mock):
    def __init__(
        self,
        clock: MockClock,
        schedule: Iterable[Tuple[float, Request]],
    ):
        super().__init__(
            get=Mock(wraps=self._get),
        )
        self._clock = clock
        self._remaining_events = list(schedule)

    def _get(self, timeout: float = 0) -> Request:
        assert self._remaining_events, "ran out of events in mock queue"

        next_event_time, next_event = self._remaining_events[0]
        time_to_next_event = next_event_time - self._clock()
        if 0 < timeout < time_to_next_event:
            self._clock.sleep(timeout)
            raise queue.Empty()

        self._remaining_events.pop(0)
        if time_to_next_event > 0:
            self._clock.sleep(time_to_next_event)
        return next_event


class TestMockRequestQueue:
    def test_smoke(self):
        clock = MockClock()
        q = MockRequestQueue(
            clock,
            [
                (t, RequestPrepare(simple_file_spec(f"req-{t}"), queue.Queue()))
                for t in [1, 3, 10, 30]
            ],
        )
        assert q.get().file_spec["name"] == "req-1"
        assert clock() == 1
        assert q.get().file_spec["name"] == "req-3"
        assert clock() == 3
        assert q.get().file_spec["name"] == "req-10"
        assert clock() == 10
        assert q.get().file_spec["name"] == "req-30"
        assert clock() == 30

    def test_raises_assertion_error_if_out_of_events(self):
        q = MockRequestQueue(MockClock(), [(1, RequestFinish())])
        q.get()
        with pytest.raises(AssertionError):
            q.get()

    def test_ticks_clock_forward(self):
        clock = MockClock()
        q = MockRequestQueue(clock, [(123, RequestFinish())])
        q.get()
        assert clock() == 123

    def test_does_not_tick_clock_backward(self):
        clock = MockClock(now=99999)
        q = MockRequestQueue(clock, [(123, RequestFinish())])
        q.get()
        assert clock() == 99999

    def test_respects_timeout(self):
        clock = MockClock()
        q = MockRequestQueue(clock, [(123, RequestFinish())])
        with pytest.raises(queue.Empty):
            q.get(timeout=8)
        assert clock() == 8
        assert q.get() == RequestFinish()
        assert clock() == 123


class TestGatherBatch:
    def test_smoke(self):
        q = Mock(
            get=Mock(
                side_effect=[
                    simple_request_prepare("a"),
                    simple_request_prepare("b"),
                    simple_request_prepare("c"),
                    RequestFinish(),
                ]
            )
        )
        done, batch = gather_batch(q, 0.1, 0.1, 100)
        assert done
        assert [f.file_spec["name"] for f in batch] == ["a", "b", "c"]

    def test_returns_empty_if_first_request_is_finish(self):
        q = Mock(
            get=Mock(
                side_effect=[
                    RequestFinish(),
                ]
            )
        )
        done, batch = gather_batch(q, 0.1, 0.1, 100)
        assert done
        assert len(batch) == 0

    def test_respects_batch_size(self):
        q = Mock(
            get=Mock(
                side_effect=[
                    simple_request_prepare("a"),
                    simple_request_prepare("b"),
                    simple_request_prepare("c"),
                ]
            )
        )
        _, batch = gather_batch(q, 0.1, 0.1, 2)
        assert len(batch) == 2
        assert q.get.call_count == 2

    def test_respects_batch_time(self):
        clock = MockClock()
        q = MockRequestQueue(
            clock=clock,
            schedule=[(t, simple_request_prepare(f"req-{t}")) for t in [5, 15, 25, 35]],
        )

        _, batch = gather_batch(
            q,
            batch_time=33,
            inter_event_time=12,
            max_batch_size=100,
            clock=clock,
        )

        assert q.get.call_args_list == [
            call(),  # finishes at t=5; 28s left in batch
            call(timeout=12),  # finishes at t=15; 18s left in batch
            call(timeout=12),  # finishes at t=25; 8s left in batch
            call(timeout=8),
        ]
        assert len(batch) == 3

    def test_respects_inter_event_time(self):
        clock = MockClock()
        q = MockRequestQueue(
            clock=clock,
            schedule=[
                (t, simple_request_prepare(f"req-{t}"))
                for t in [10, 30, 60, 100, 150, 210, 280]
                # diffs:    20  30  40   50   60   70
            ],
        )

        _, batch = gather_batch(
            q,
            batch_time=1000,
            inter_event_time=33,
            max_batch_size=100,
            clock=clock,
        )

        assert q.get.call_args_list == [
            call(),  # waited 10s, next wait is 20s
            call(timeout=33),  # waited 20s, next wait is 30s
            call(timeout=33),  # waited 30s, next wait is 40s
            call(timeout=33),  # waited 33s, then raised Empty
        ]
        assert len(batch) == 3

    def test_ends_early_if_request_finish(self):
        q = Mock(
            get=Mock(
                side_effect=[
                    simple_request_prepare("a"),
                    RequestFinish(),
                    simple_request_prepare("b"),
                ]
            )
        )
        done, batch = gather_batch(q, 0.1, 0.1, 100)
        assert done
        assert [f.file_spec["name"] for f in batch] == ["a"]
        assert q.get.call_count == 2


class TestStepPrepare:
    @staticmethod
    def _bg_prepare_sync(
        step_prepare: StepPrepare, *args, **kwargs
    ) -> "concurrent.futures.Future[ResponsePrepare]":
        """Starts prepare_sync running in the background.

        Don't call this directly; use the `prepare` fixture instead, to ensure that
        whatever logic you're testing works with both sync and async impls.

        If you're writing a test that only cares about the sync impl, you should
        probably just call `step_prepare.prepare_sync` directly.
        """
        enqueued = threading.Event()
        future = concurrent.futures.Future()

        def prepare_and_resolve():
            q = step_prepare.prepare_sync(*args, **kwargs)
            enqueued.set()
            future.set_result(q.get())

        threading.Thread(
            name="prepare_and_resolve",
            target=prepare_and_resolve,
            daemon=True,
        ).start()

        enqueued.wait()
        return future

    @staticmethod
    def _bg_prepare_async(
        step_prepare: StepPrepare, *args, **kwargs
    ) -> "concurrent.futures.Future[ResponsePrepare]":
        """Starts prepare_async running in the background.

        Don't call this directly; use the `prepare` fixture instead, to ensure that
        whatever logic you're testing works with both sync and async impls.

        If you're writing a test that only cares about the async impl, you should
        probably just call `step_prepare.prepare_async` directly.
        """
        enqueued = threading.Event()
        future = concurrent.futures.Future()

        async def prepare_and_resolve():
            prepare_async_future = step_prepare.prepare_async(*args, **kwargs)
            # Note: ^that's an asyncio.Future, not a concurrent.futures.Future
            enqueued.set()
            future.set_result(await prepare_async_future)

        threading.Thread(
            name="prepare_and_resolve",
            target=asyncio.new_event_loop().run_until_complete,
            args=[prepare_and_resolve()],
            daemon=True,
        ).start()

        enqueued.wait()
        return future

    @pytest.fixture(params=["sync", "async"])
    def prepare(self, request) -> "PrepareFixture":
        """Fixture to kick off prepare_sync or prepare_async in the background.

        Tests that use this fixture will be run twice: once using prepare_sync,
        once using prepare_async.

        Example usage:

            def test_smoke(prepare: "PrepareFixture"):
                step_prepare = StepPrepare(...)
                step_prepare.start()
                res = prepare(step_prepare, simple_file_spec(name="foo")).result()
                assert res.birth_artifact_id == ...
        """
        if request.param == "sync":
            return self._bg_prepare_sync
        elif request.param == "async":
            return self._bg_prepare_async
        else:
            raise ValueError(f"Unknown prepare mode: {request.param}")

    def test_smoke(self, prepare: "PrepareFixture"):
        caf_result = mock_create_artifact_files_result(["foo"])
        api = Mock(create_artifact_files=Mock(return_value=caf_result))

        step_prepare = StepPrepare(
            api=api, batch_time=1e-12, inter_event_time=1e-12, max_batch_size=1
        )
        step_prepare.start()

        res = prepare(step_prepare, simple_file_spec(name="foo")).result()
        step_prepare.finish()

        assert res == ResponsePrepare(
            upload_url=caf_result["foo"]["uploadUrl"],
            upload_headers=caf_result["foo"]["uploadHeaders"],
            birth_artifact_id=caf_result["foo"]["artifact"]["id"],
        )

    def test_batches_requests(self, prepare: "PrepareFixture"):
        caf_result = mock_create_artifact_files_result(["a", "b"])
        api = Mock(create_artifact_files=Mock(return_value=caf_result))

        step_prepare = StepPrepare(
            api=api, batch_time=1, inter_event_time=1, max_batch_size=10
        )
        step_prepare.start()

        future_a = prepare(step_prepare, simple_file_spec(name="a"))
        future_b = prepare(step_prepare, simple_file_spec(name="b"))
        step_prepare.finish()

        res_a = future_a.result()
        res_b = future_b.result()

        assert res_a.upload_url == caf_result["a"]["uploadUrl"]
        assert res_b.upload_url == caf_result["b"]["uploadUrl"]

        # make sure the URLs are different, just in case the fixture returns a constant
        assert res_a.upload_url != res_b.upload_url

        api.create_artifact_files.assert_called_once()

    def test_finish_waits_for_pending_requests(self, prepare: "PrepareFixture"):
        caf_result = mock_create_artifact_files_result(["a", "b"])
        api = Mock(create_artifact_files=Mock(return_value=caf_result))

        step_prepare = StepPrepare(
            api=api, batch_time=1, inter_event_time=1, max_batch_size=10
        )
        step_prepare.start()

        res_future = prepare(step_prepare, simple_file_spec(name="a"))

        with pytest.raises(concurrent.futures.TimeoutError):
            res_future.result(timeout=0.2)

        assert step_prepare.is_alive()

        step_prepare.finish()

        res = res_future.result(timeout=5)

        assert res.upload_url == caf_result["a"]["uploadUrl"]

        step_prepare._thread.join()
        assert not step_prepare.is_alive()
