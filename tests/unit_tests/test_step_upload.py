import queue
import random
import threading
import time
from pathlib import Path
from typing import Any, MutableSequence, Optional, Sequence
from unittest.mock import Mock

import pytest
from wandb.filesync import stats
from wandb.filesync.step_upload import (
    Event,
    RequestCommitArtifact,
    RequestFinish,
    RequestUpload,
    StepUpload,
)


def mock_upload_urls(
    project: str,
    files,
    run=None,
    entity=None,
    description=None,
):
    return (
        "some-bucket",
        [],
        {file: {"url": f"http://localhost/{file}"} for file in files},
    )


def make_tmp_file(tmp_path: Path) -> Path:
    f = tmp_path / str(random.random())
    f.write_text(str(random.random()))
    return f


def make_step_upload(
    **kwargs: Any,
) -> "StepUpload":
    return StepUpload(
        **{
            "api": Mock(),
            "stats": stats.Stats(),
            "event_queue": queue.Queue(),
            "max_jobs": 10,
            "file_stream": Mock(),
            **kwargs,
        }
    )


def make_request_upload(path: Path, **kwargs: Any) -> RequestUpload:
    return RequestUpload(
        path=path,
        **{
            "save_name": str(path),
            "artifact_id": None,
            "md5": None,
            "copied": False,
            "save_fn": None,
            "digest": None,
            **kwargs,
        },
    )


def make_request_commit(artifact_id: str, **kwargs: Any) -> RequestCommitArtifact:
    return RequestCommitArtifact(
        artifact_id=artifact_id,
        **{"before_commit": None, "on_commit": None, "finalize": True, **kwargs},
    )


def finish_and_wait(command_queue: queue.Queue):
    done = threading.Event()
    command_queue.put(RequestFinish(callback=done.set))
    assert done.wait(2)


class UploadBlockingMockApi(Mock):
    def __init__(self, *args, **kwargs):

        super().__init__(
            *args,
            **kwargs,
            upload_urls=Mock(wraps=mock_upload_urls),
            upload_file_retry=Mock(wraps=self._mock_upload),
        )

        self.mock_upload_file_waiters: MutableSequence[threading.Event] = []
        self.mock_upload_started = threading.Condition()

    def wait_for_upload(self, timeout: float) -> Optional[threading.Event]:
        with self.mock_upload_started:
            if not self.mock_upload_started.wait_for(
                lambda: len(self.mock_upload_file_waiters) > 0,
                timeout=timeout,
            ):
                return None
            return self.mock_upload_file_waiters.pop()

    def _mock_upload(self, *args, **kwargs):
        ev = threading.Event()
        with self.mock_upload_started:
            self.mock_upload_file_waiters.append(ev)
            self.mock_upload_started.notify_all()
        ev.wait()


class TestFinish:
    @pytest.mark.parametrize(
        ["commands"],
        [
            ([],),
            ([make_request_upload(Path("some/path"))],),
            ([make_request_upload(Path("some/path"), artifact_id="artid")],),
            ([make_request_commit("artid")],),
            (
                [
                    make_request_upload(Path("some/path"), artifact_id="artid"),
                    make_request_commit("artid"),
                ],
            ),
        ],
    )
    def test_finishes(
        self,
        commands: Sequence[Event],
    ):
        q = queue.Queue()
        for command in commands:
            q.put(command)

        step_upload = make_step_upload(event_queue=q)
        step_upload.start()

        finish_and_wait(q)

    def test_no_finish_until_jobs_done(
        self,
        tmp_path: Path,
    ):
        api = UploadBlockingMockApi()

        done = threading.Event()
        q = queue.Queue()
        q.put(make_request_upload(make_tmp_file(tmp_path)))
        q.put(RequestFinish(callback=done.set))

        step_upload = make_step_upload(api=api, event_queue=q)
        step_upload.start()

        unblock = api.wait_for_upload(2)
        assert not done.wait(0.1)
        unblock.set()
        assert done.wait(2)


class TestUpload:
    def test_upload(
        self,
        tmp_path: Path,
    ):
        api = Mock(
            upload_urls=mock_upload_urls,
            upload_file_retry=Mock(),
        )

        q = queue.Queue()
        cmd = make_request_upload(make_tmp_file(tmp_path))
        q.put(cmd)

        step_upload = make_step_upload(api=api, event_queue=q)
        step_upload.start()

        finish_and_wait(q)
        api.upload_file_retry.assert_called_once()
        assert (
            api.upload_file_retry.call_args[0][0]
            == mock_upload_urls("my-proj", [cmd.save_name])[2][cmd.save_name]["url"]
        )

    def test_reuploads_if_event_during_upload(
        self,
        tmp_path: Path,
    ):
        f = make_tmp_file(tmp_path)

        api = UploadBlockingMockApi()

        q = queue.Queue()
        q.put(make_request_upload(f))

        step_upload = make_step_upload(api=api, event_queue=q)
        step_upload.start()

        unblock = api.wait_for_upload(2)
        q.put(make_request_upload(f))
        # TODO(spencerpearson): if we RequestUpload _several_ more times,
        # it seems like we should still only reupload once?
        # But as of 2022-12-15, the behavior is to reupload several more times,
        # the not-yet-actionable requests not being deduped against each other.

        time.sleep(0.1)  # TODO: better way to wait for the message to be processed
        assert api.upload_file_retry.call_count == 1
        unblock.set()

        unblock = api.wait_for_upload(2)
        assert unblock
        unblock.set()

        finish_and_wait(q)
        assert api.upload_file_retry.call_count == 2

    @pytest.mark.parametrize("copied", [True, False])
    def test_deletes_after_upload_iff_copied(
        self,
        tmp_path: Path,
        copied: bool,
    ):

        f = make_tmp_file(tmp_path)

        api = UploadBlockingMockApi()

        q = queue.Queue()
        q.put(make_request_upload(f, copied=copied))

        step_upload = make_step_upload(api=api, event_queue=q)
        step_upload.start()

        unblock = api.wait_for_upload(2)
        assert f.exists()

        unblock.set()

        finish_and_wait(q)

        if copied:
            assert not f.exists()
        else:
            assert f.exists()


class TestArtifactCommit:
    @pytest.mark.parametrize(
        ["finalize"],
        [(True,), (False,)],
    )
    def test_commits_iff_finalize(
        self,
        finalize: bool,
    ):

        api = Mock()

        q = queue.Queue()
        q.put(make_request_commit("my-art", finalize=finalize))

        step_upload = make_step_upload(api=api, event_queue=q)
        step_upload.start()

        finish_and_wait(q)

        if finalize:
            api.commit_artifact.assert_called_once()
            assert api.commit_artifact.call_args[0][0] == "my-art"
        else:
            api.commit_artifact.assert_not_called()

    def test_no_commit_until_uploads_done(
        self,
        tmp_path: Path,
    ):
        api = UploadBlockingMockApi()

        q = queue.Queue()
        q.put(make_request_upload(make_tmp_file(tmp_path), artifact_id="my-art"))
        q.put(make_request_commit("my-art"))

        step_upload = make_step_upload(api=api, event_queue=q)
        step_upload.start()

        unblock = api.wait_for_upload(2)

        time.sleep(
            0.1
        )  # TODO: better way to wait for the Commit message to be processed
        api.commit_artifact.assert_not_called()

        unblock.set()
        finish_and_wait(q)
        api.commit_artifact.assert_called_once()

    def test_no_commit_if_upload_fails(
        self,
        tmp_path: Path,
    ):
        def mock_upload(*args, **kwargs):
            raise Exception("upload failed")

        api = Mock(
            upload_urls=mock_upload_urls,
            upload_file_retry=mock_upload,
        )

        q = queue.Queue()
        q.put(make_request_upload(make_tmp_file(tmp_path), artifact_id="my-art"))
        q.put(make_request_commit("my-art"))

        step_upload = make_step_upload(api=api, event_queue=q)
        step_upload.start()

        finish_and_wait(q)
        api.commit_artifact.assert_not_called()

    def test_calls_callbacks(self):

        events = []
        api = Mock(
            commit_artifact=lambda *args, **kwargs: events.append("commit"),
        )

        q = queue.Queue()
        q.put(
            make_request_commit(
                "my-art",
                before_commit=lambda: events.append("before"),
                on_commit=lambda: events.append("on"),
                finalize=True,
            )
        )

        step_upload = make_step_upload(api=api, event_queue=q)
        step_upload.start()

        finish_and_wait(q)

        assert events == ["before", "commit", "on"]


def test_enforces_max_jobs(
    tmp_path: Path,
):
    max_jobs = 3

    q = queue.Queue()

    api = UploadBlockingMockApi()

    def add_job():
        q.put(make_request_upload(make_tmp_file(tmp_path)))

    step_upload = make_step_upload(api=api, event_queue=q, max_jobs=max_jobs)
    step_upload.start()

    waiters = []

    # first few jobs should start without blocking
    for _ in range(max_jobs):
        add_job()
        waiters.append(api.wait_for_upload(0.1))

    # next job should block...
    add_job()
    assert not api.wait_for_upload(0.1)

    # ...until we release one of the first jobs
    waiters.pop().set()
    waiters.append(api.wait_for_upload(0.1))

    # let all jobs finish, to release the threads
    for w in waiters:
        w.set()

    finish_and_wait(q)


def test_is_alive_until_last_job_finishes(
    tmp_path: Path,
):
    q = queue.Queue()

    api = UploadBlockingMockApi()

    step_upload = make_step_upload(api=api, event_queue=q)
    step_upload.start()

    q.put(make_request_upload(make_tmp_file(tmp_path)))
    unblock = api.wait_for_upload(2)

    done = threading.Event()
    q.put(RequestFinish(callback=done.set))

    time.sleep(0.1)  # TODO: better way to wait for the message to be processed
    assert step_upload.is_alive()

    unblock.set()
    assert done.wait(2)
    assert not step_upload.is_alive()
