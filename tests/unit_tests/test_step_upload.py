import time
import queue
from pathlib import Path
import random
import threading
from typing import TYPE_CHECKING, Any, Iterator, MutableSequence, Sequence, Type
from unittest.mock import Mock
import pytest
from wandb.filesync import stats
from wandb.filesync.step_upload import (
    StepUpload,
    Event,
    RequestFinish,
    RequestCommitArtifact,
    RequestUpload,
)

if TYPE_CHECKING:
    from wandb.filesync.step_upload import AbstractStepUpload


@pytest.fixture(params=[
    StepUpload,
])
def step_upload_cls(request) -> Iterator[Type["AbstractStepUpload"]]:
    return request.param


def mock_upload_urls(
        project: str,
        files,
        run=None,
        entity=None,
        description=None,
):
    return "some-bucket", [], {
        file: {"url": f"http://localhost/{file}"}
        for file in files
    }


def make_tmp_file(tmp_path: Path) -> Path:
    f = tmp_path / str(random.random())
    f.write_text(str(random.random()))
    return f


def make_step_upload(
    cls: Type["AbstractStepUpload"],
    **kwargs: Any,
) -> "AbstractStepUpload":
    kwargs.setdefault("api", Mock())
    kwargs.setdefault("stats", stats.Stats())
    kwargs.setdefault("event_queue", queue.Queue())
    kwargs.setdefault("max_jobs", 10)
    kwargs.setdefault("file_stream", Mock())
    return cls(**kwargs)


def finish_and_wait(command_queue: queue.Queue):
    done = threading.Event()
    command_queue.put(RequestFinish(callback=done.set))
    assert done.wait(2)


class TestFinish:

    @pytest.mark.parametrize(
        ["commands"],
        [
            ([],),
            ([
                RequestUpload(path="some/path", save_name="some/savename", artifact_id="artid", md5="123", copied=False, save_fn=None, digest=None),
            ],),
            ([
                RequestCommitArtifact(artifact_id=None, before_commit=None, on_commit=None, finalize=True),
            ],),
            ([
                RequestCommitArtifact(artifact_id="artid", before_commit=None, on_commit=None, finalize=True),
            ],),
            ([
                RequestUpload(path="some/path", save_name="some/savename", artifact_id="artid", md5="123", copied=False, save_fn=None, digest=None),
                RequestCommitArtifact(artifact_id="artid", before_commit=None, on_commit=None, finalize=True),
            ],),
        ],
    )
    def test_finishes(
        self,
        step_upload_cls: Type["AbstractStepUpload"],
        commands: Sequence[Event],
    ):
        q = queue.Queue()
        for command in commands:
            q.put(command)

        step_upload = make_step_upload(step_upload_cls, event_queue=q)
        step_upload.start()

        finish_and_wait(q)

    def test_no_finish_until_jobs_done(
        self,
        step_upload_cls: Type["AbstractStepUpload"],
        tmp_path: Path,
    ):
        upload_started = threading.Event()
        upload_finished = threading.Event()

        def mock_upload(*args, **kwargs):
            upload_started.set()
            upload_finished.wait()

        api = Mock(
            upload_urls=mock_upload_urls,
            upload_file_retry=mock_upload,
        )

        done = threading.Event()
        q = queue.Queue()
        q.put(RequestUpload(path=str(make_tmp_file(tmp_path)), save_name="save_name", artifact_id=None, md5=None, copied=False, save_fn=None, digest=None))
        q.put(RequestFinish(callback=done.set))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        assert upload_started.wait(2)
        assert not done.wait(0.1)
        upload_finished.set()
        assert done.wait(2)


class TestUpload:

    def test_upload(
        self,
        step_upload_cls: Type["AbstractStepUpload"],
        tmp_path: Path,
    ):
        api = Mock(
            upload_urls=mock_upload_urls,
            upload_file_retry=Mock(),
        )

        q = queue.Queue()
        q.put(RequestUpload(path=str(make_tmp_file(tmp_path)), save_name="save_name", artifact_id=None, md5=None, copied=False, save_fn=None, digest=None))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        finish_and_wait(q)
        api.upload_file_retry.assert_called_once()
        assert api.upload_file_retry.call_args[0][0] == mock_upload_urls("my-proj", ["save_name"])[2]["save_name"]["url"]

    def test_reuploads_if_event_during_upload(
        self,
        step_upload_cls: Type["AbstractStepUpload"],
        tmp_path: Path,
    ):
        f = make_tmp_file(tmp_path)

        upload_started = threading.Event()
        upload_finished = threading.Event()

        def mock_upload(*args, **kwargs):
            upload_started.set()
            upload_finished.wait()

        api = Mock(
            upload_urls=mock_upload_urls,
            upload_file_retry=Mock(wraps=mock_upload),
        )

        q = queue.Queue()
        q.put(RequestUpload(path=str(f), save_name="save_name", artifact_id=None, md5=None, copied=False, save_fn=None, digest=None))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        assert upload_started.wait(2)
        q.put(RequestUpload(path=str(f), save_name="save_name", artifact_id=None, md5=None, copied=False, save_fn=None, digest=None))
        # TODO(spencerpearson): if we RequestUpload _several_ more times,
        # it seems like we should still only reupload once?
        # But as of 2022-12-15, the behavior is to reupload several more times,
        # the not-yet-actionable requests no being deduped against each other.

        time.sleep(0.1)  # TODO: better way to wait for the message to be processed
        upload_finished.set()

        finish_and_wait(q)
        assert api.upload_file_retry.call_count == 2

    @pytest.mark.parametrize("copied", [True, False])
    def test_deletes_after_upload_iff_copied(
        self,
        step_upload_cls: Type["AbstractStepUpload"],
        tmp_path: Path,
        copied: bool,
    ):

        f = make_tmp_file(tmp_path)

        upload_started = threading.Event()
        upload_finished = threading.Event()

        def mock_upload(*args, **kwargs):
            upload_started.set()
            upload_finished.wait()

        api = Mock(
            upload_urls=mock_upload_urls,
            upload_file_retry=Mock(wraps=mock_upload),
        )

        q = queue.Queue()
        q.put(RequestUpload(path=str(f), save_name="save_name", artifact_id=None, md5=None, copied=copied, save_fn=None, digest=None))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        assert upload_started.wait(2)
        assert f.exists()

        upload_finished.set()

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
        step_upload_cls: Type["AbstractStepUpload"],
        finalize: bool,
    ):

        api = Mock()

        q = queue.Queue()
        q.put(RequestCommitArtifact(artifact_id="my-art", before_commit=None, on_commit=None, finalize=finalize))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        finish_and_wait(q)

        if finalize:
            api.commit_artifact.assert_called_once()
            assert api.commit_artifact.call_args[0][0] == "my-art"
        else:
            api.commit_artifact.assert_not_called()

    def test_no_commit_until_uploads_done(
        self,
        step_upload_cls: Type["AbstractStepUpload"],
        tmp_path: Path,
    ):
        upload_started = threading.Event()
        upload_finished = threading.Event()

        def mock_upload(*args, **kwargs):
            upload_started.set()
            upload_finished.wait()

        api = Mock(
            upload_urls=mock_upload_urls,
            upload_file_retry=mock_upload,
        )

        q = queue.Queue()
        q.put(RequestUpload(path=str(make_tmp_file(tmp_path)), save_name="save_name", artifact_id="my-art", md5=None, copied=False, save_fn=None, digest=None))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        assert upload_started.wait(2)
        q.put(RequestCommitArtifact(artifact_id="my-art", before_commit=None, on_commit=None, finalize=True))
        time.sleep(0.1)  # TODO: better way to wait for the message to be processed
        api.commit_artifact.assert_not_called()

        upload_finished.set()
        finish_and_wait(q)
        api.commit_artifact.assert_called_once()

    def test_no_commit_if_upload_fails(
        self,
        step_upload_cls: Type["AbstractStepUpload"],
        tmp_path: Path,
    ):
        def mock_upload(*args, **kwargs):
            raise Exception("upload failed")

        api = Mock(
            upload_urls=mock_upload_urls,
            upload_file_retry=mock_upload,
        )

        q = queue.Queue()
        q.put(RequestUpload(path=str(make_tmp_file(tmp_path)), save_name="save_name", artifact_id="my-art", md5=None, copied=False, save_fn=None, digest=None))
        q.put(RequestCommitArtifact(artifact_id="my-art", before_commit=None, on_commit=None, finalize=True))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        finish_and_wait(q)
        api.commit_artifact.assert_not_called()

    def test_calls_callbacks(self, step_upload_cls: Type["AbstractStepUpload"]):

        events = []
        api = Mock(
            commit_artifact=lambda *args, **kwargs: events.append("commit"),
        )

        q = queue.Queue()
        q.put(RequestCommitArtifact(artifact_id="my-art", before_commit=lambda: events.append("before"), on_commit=lambda: events.append("on"), finalize=True))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        finish_and_wait(q)

        assert events == ["before", "commit", "on"]



def test_enforces_max_jobs(
    step_upload_cls: Type["AbstractStepUpload"],
    tmp_path: Path,
):
    max_jobs = 3

    q = queue.Queue()

    waiters: MutableSequence[threading.Event] = []
    upload_started = threading.Condition()

    def mock_upload(*args, **kwargs):
        with upload_started:
            cont = threading.Event()
            waiters.append(cont)
            upload_started.notify_all()
        cont.wait()

    api = Mock(
        upload_urls=mock_upload_urls,
        upload_file_retry=mock_upload
    )

    def add_job():
        f = make_tmp_file(tmp_path)
        q.put(RequestUpload(path=str(f), save_name=str(f), artifact_id=None, md5=None, copied=False, save_fn=None, digest=None))

    step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q, max_jobs=max_jobs)
    step_upload.start()

    with upload_started:

        # first few jobs should start without blocking
        for i in range(max_jobs):
            add_job()
            assert upload_started.wait(0.5), i

        # next job should block...
        add_job()
        assert not upload_started.wait(0.1)

        # ...until we release one of the first jobs
        for w in waiters:
            w.set()
        assert upload_started.wait(2)

    for w in waiters:
        w.set()

    finish_and_wait(q)

def test_is_alive_until_last_job_finishes(
    step_upload_cls: Type["AbstractStepUpload"],
    tmp_path: Path,
):
    q = queue.Queue()

    upload_started = threading.Event()
    upload_finished = threading.Event()

    def mock_upload(*args, **kwargs):
        upload_started.set()
        upload_finished.wait()

    api = Mock(
        upload_urls=mock_upload_urls,
        upload_file_retry=mock_upload
    )

    step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
    step_upload.start()

    f = make_tmp_file(tmp_path)
    q.put(RequestUpload(path=str(f), save_name=str(f), artifact_id=None, md5=None, copied=False, save_fn=None, digest=None))
    assert upload_started.wait(2)

    done = threading.Event()
    q.put(RequestFinish(callback=done.set))

    time.sleep(0.1)  # TODO: better way to wait for the message to be processed
    assert step_upload.is_alive()

    upload_finished.set()
    assert done.wait(2)
    assert not step_upload.is_alive()
