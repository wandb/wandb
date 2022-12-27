import queue
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable, MutableSequence, Optional
from unittest.mock import Mock

import pytest
from wandb.filesync import stats
from wandb.filesync.step_upload import (
    RequestCommitArtifact,
    RequestFinish,
    RequestUpload,
    StepUpload,
)
from wandb.sdk.internal import file_stream, internal_api


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


def mock_upload_file_retry(url, file, callback, extra_headers):
    size = len(file.read())
    callback(size, size)


def make_tmp_file(tmp_path: Path) -> Path:
    f = tmp_path / str(random.random())
    f.write_text(str(random.random()))
    return f


def make_step_upload(
    **kwargs: Any,
) -> "StepUpload":
    return StepUpload(
        **{
            "api": Mock(
                spec=internal_api.Api,
                upload_urls=Mock(wraps=mock_upload_urls),
                upload_file_retry=Mock(wraps=mock_upload_file_retry),
            ),
            "stats": Mock(spec=stats.Stats),
            "event_queue": queue.Queue(),
            "max_jobs": 10,
            "file_stream": Mock(spec=file_stream.FileStreamApi),
            **kwargs,
        }
    )


def make_request_upload(path: Path, **kwargs: Any) -> RequestUpload:
    return RequestUpload(
        path=str(path),
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
    def test_finishes_if_first_message(
        self,
    ):
        q = queue.Queue()
        step_upload = make_step_upload(event_queue=q)
        step_upload.start()

        finish_and_wait(q)

    def test_finishes_after_uploads(
        self,
        tmp_path: Path,
    ):
        q = queue.Queue()
        q.put(make_request_upload(make_tmp_file(tmp_path)))
        q.put(make_request_upload(make_tmp_file(tmp_path)))
        q.put(make_request_upload(make_tmp_file(tmp_path)))
        step_upload = make_step_upload(event_queue=q)
        step_upload.start()

        finish_and_wait(q)

    def test_finishes_after_upload_urls(
        self,
        tmp_path: Path,
    ):
        q = queue.Queue()
        q.put(make_request_upload(make_tmp_file(tmp_path)))
        step_upload = make_step_upload(
            event_queue=q,
            api=Mock(
                upload_urls=Mock(side_effect=Exception("upload_urls failed")),
            ),
        )
        step_upload.start()

        finish_and_wait(q)

    def test_finishes_after_failed_upload(
        self,
        tmp_path: Path,
    ):
        q = queue.Queue()
        q.put(make_request_upload(make_tmp_file(tmp_path)))
        step_upload = make_step_upload(
            event_queue=q,
            api=Mock(
                upload_urls=mock_upload_urls,
                upload_file_retry=Mock(side_effect=Exception("upload failed")),
            ),
        )
        step_upload.start()

        finish_and_wait(q)

    def test_finishes_after_artifact_commit(
        self,
    ):
        q = queue.Queue()
        q.put(make_request_commit("my-artifact"))
        step_upload = make_step_upload(event_queue=q)
        step_upload.start()

        finish_and_wait(q)

    def test_finishes_after_failed_artifact_commit(
        self,
    ):
        q = queue.Queue()
        q.put(make_request_commit("my-artifact"))
        step_upload = make_step_upload(
            event_queue=q,
            api=Mock(
                upload_urls=mock_upload_urls,
                commit_artifact=Mock(side_effect=Exception("commit failed")),
            ),
        )
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

    @pytest.mark.parametrize(
        "api",
        [
            Mock(upload_urls=Mock(side_effect=Exception("upload_urls failed"))),
            Mock(
                upload_urls=mock_upload_urls,
                upload_file_retry=Mock(
                    side_effect=Exception("upload_file_retry failed")
                ),
            ),
        ],
    )
    def test_error_doesnt_stop_future_uploads(
        self,
        tmp_path: Path,
        api: Mock,
    ):
        q = queue.Queue()
        q.put(make_request_upload(make_tmp_file(tmp_path)))
        q.put(make_request_upload(make_tmp_file(tmp_path)))

        step_upload = make_step_upload(api=api, event_queue=q, max_jobs=1)
        step_upload.start()

        finish_and_wait(q)

    class TestStats:
        @pytest.mark.parametrize(
            "make_save_fn",
            [
                lambda _: None,
                lambda size: lambda progress: progress(size, size),
            ],
        )
        def test_updates_on_read(
            self,
            tmp_path: Path,
            make_save_fn: Callable[[int], Optional[Callable[[int, int], None]]],
        ):
            f = make_tmp_file(tmp_path)

            q = queue.Queue()
            cmd = make_request_upload(f, save_fn=make_save_fn(f.stat().st_size))
            q.put(cmd)

            mock_stats = Mock(spec=stats.Stats)

            step_upload = make_step_upload(event_queue=q, stats=mock_stats)
            step_upload.start()

            finish_and_wait(q)

            mock_stats.update_uploaded_file.assert_called_with(str(f), f.stat().st_size)

        @pytest.mark.parametrize(
            "save_fn",
            [
                None,
                Mock(side_effect=Exception("save_fn failed")),
            ],
        )
        def test_updates_on_failure(
            self,
            tmp_path: Path,
            save_fn: Optional[Callable[[int, int], None]],
        ):
            f = make_tmp_file(tmp_path)

            api = Mock(
                upload_urls=mock_upload_urls,
                upload_file_retry=Mock(
                    side_effect=Exception("upload_file_retry failed")
                ),
            )

            q = queue.Queue()
            cmd = make_request_upload(f, save_fn=save_fn)
            q.put(cmd)

            mock_stats = Mock(spec=stats.Stats)

            step_upload = make_step_upload(event_queue=q, stats=mock_stats, api=api)
            step_upload.start()

            finish_and_wait(q)

            mock_stats.update_failed_file.assert_called_once_with(str(f))

        @pytest.mark.parametrize("deduped", [True, False])
        def test_update_on_deduped(
            self,
            tmp_path: Path,
            deduped: bool,
        ):
            f = make_tmp_file(tmp_path)

            q = queue.Queue()
            cmd = make_request_upload(f, save_fn=Mock(return_value=deduped))
            q.put(cmd)

            mock_stats = Mock(spec=stats.Stats)

            step_upload = make_step_upload(event_queue=q, stats=mock_stats)
            step_upload.start()

            finish_and_wait(q)

            if deduped:
                mock_stats.set_file_deduped.assert_called_once_with(str(f))
            else:
                mock_stats.set_file_deduped.assert_not_called()

    @pytest.mark.parametrize(
        ["save_fn", "api", "success"],
        [
            (
                None,
                Mock(upload_urls=mock_upload_urls, upload_file_retry=mock_upload_file_retry),
                True,
            ),
            (
                None,
                Mock(upload_urls=Mock(side_effect=Exception("upload_urls failed"))),
                False,
            ),
            (
                None,
                Mock(upload_urls=mock_upload_urls, upload_file_retry=Mock(side_effect=Exception("upload_file_retry failed"))),
                False,
            ),
            (
                Mock(return_value=False), Mock(), True,
            ),
            (
                Mock(return_value=True), Mock(), True,
            ),
            (
                Mock(side_effect=Exception("save_fn failed")), Mock(), False,
            ),
        ]
    )
    def test_notifies_file_stream_on_success(
        self,
        tmp_path: Path,
        save_fn: Optional[Callable[[int, int], bool]],
        api: Mock,
        success: bool,
    ):
        f = make_tmp_file(tmp_path)

        q = queue.Queue()
        cmd = make_request_upload(f, save_fn=save_fn)
        q.put(cmd)

        mock_file_stream = Mock(spec=file_stream.FileStreamApi)

        step_upload = make_step_upload(event_queue=q, file_stream=mock_file_stream, api=api)
        step_upload.start()

        finish_and_wait(q)

        if success:
            mock_file_stream.push_success.assert_called_once_with(cmd.artifact_id, cmd.save_name)
        else:
            mock_file_stream.push_success.assert_not_called()


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

    @pytest.mark.parametrize(
        "commit_exc",
        [None, Exception("commit failed")],
    )
    def test_calls_callbacks(self, commit_exc: Optional[Exception]):

        events = []

        def mock_commit_artifact(*args, **kwargs):
            events.append("commit")
            if commit_exc:
                raise commit_exc

        api = Mock(commit_artifact=mock_commit_artifact)

        q = queue.Queue()
        q.put(
            make_request_commit(
                "my-art",
                before_commit=lambda: events.append("before"),
                on_commit=lambda exc: events.append(("on", exc)),
                finalize=True,
            )
        )

        step_upload = make_step_upload(api=api, event_queue=q)
        step_upload.start()

        finish_and_wait(q)

        assert events == ["before", "commit", ("on", commit_exc)]


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
