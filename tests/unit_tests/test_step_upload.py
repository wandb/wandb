import time
import queue
from pathlib import Path
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
        done = threading.Event()
        q = queue.Queue()
        for command in commands:
            q.put(command)
        q.put(RequestFinish(callback=done.set))

        step_upload = make_step_upload(step_upload_cls, event_queue=q)
        step_upload.start()

        assert done.wait(2)

    def test_no_finish_until_jobs_done(
        self,
        step_upload_cls: Type["AbstractStepUpload"],
        tmp_path: Path,
    ):
        f = tmp_path / "file"
        f.write_text("stuff")

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
        q.put(RequestUpload(path=str(f), save_name="save_name", artifact_id=None, md5=None, copied=False, save_fn=None, digest=None))
        q.put(RequestFinish(callback=done.set))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        assert upload_started.wait(2)
        assert not done.wait(0.1)
        upload_finished.set()
        assert done.wait(2)


class TestUpload:
    def test_reuploads_if_event_during_upload(
        self,
        step_upload_cls: Type["AbstractStepUpload"],
        tmp_path: Path,
    ):
        f = tmp_path / "file"
        f.write_text("stuff")

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

        time.sleep(0.1)  # TODO: better way to wait for the message to be processed
        upload_finished.set()

        done = threading.Event()
        q.put(RequestFinish(callback=done.set))
        assert done.wait(2)
        assert api.upload_file_retry.call_count == 2


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

        done = threading.Event()
        q = queue.Queue()
        q.put(RequestCommitArtifact(artifact_id="my-art", before_commit=None, on_commit=None, finalize=finalize))
        q.put(RequestFinish(callback=done.set))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        assert done.wait(2)

        if finalize:
            assert api.commit_artifact.call_args[0][0] == "my-art"
        else:
            api.commit_artifact.assert_not_called()

    def test_no_commit_until_uploads_done(
        self,
        step_upload_cls: Type["AbstractStepUpload"],
        tmp_path: Path,
    ):
        f = tmp_path / "file"
        f.write_text("stuff")

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
        q.put(RequestUpload(path=str(f), save_name="save_name", artifact_id="my-art", md5=None, copied=False, save_fn=None, digest=None))
        q.put(RequestCommitArtifact(artifact_id="my-art", before_commit=None, on_commit=None, finalize=True))
        q.put(RequestFinish(callback=done.set))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        assert upload_started.wait(2)
        assert not done.wait(0.1)
        api.commit_artifact.assert_not_called()

        upload_finished.set()
        assert done.wait(2)
        api.commit_artifact.assert_called_once()

    def test_no_commit_if_upload_fails(
        self,
        step_upload_cls: Type["AbstractStepUpload"],
        tmp_path: Path,
    ):
        f = tmp_path / "file"
        f.write_text("stuff")

        def mock_upload(*args, **kwargs):
            raise Exception("upload failed")

        api = Mock(
            upload_urls=mock_upload_urls,
            upload_file_retry=mock_upload,
        )

        done = threading.Event()
        q = queue.Queue()
        q.put(RequestUpload(path=str(f), save_name="save_name", artifact_id="my-art", md5=None, copied=False, save_fn=None, digest=None))
        q.put(RequestCommitArtifact(artifact_id="my-art", before_commit=None, on_commit=None, finalize=True))
        q.put(RequestFinish(callback=done.set))

        step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q)
        step_upload.start()

        assert done.wait(2)
        api.commit_artifact.assert_not_called()


def test_enforces_max_jobs(
    step_upload_cls: Type["AbstractStepUpload"],
    tmp_path: Path,
):
    max_jobs = 3
    n_uploads = 5

    files = [tmp_path / f"file-{i}" for i in range(n_uploads)]
    for i, f in enumerate(files):
        f.write_text(f"file {i}")

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

    step_upload = make_step_upload(step_upload_cls, api=api, event_queue=q, max_jobs=max_jobs)
    for i, f in enumerate(files):
        q.put(RequestUpload(path=str(f), save_name=f"save_name-{i}", artifact_id=None, md5=None, copied=False, save_fn=None, digest=None))

    done = threading.Event()
    q.put(RequestFinish(callback=done.set))

    step_upload.start()

    with upload_started:
        while len(waiters) < max_jobs:
            upload_started.wait(2)

        assert not upload_started.wait(0.1)

    for w in waiters:
        w.set()

    with upload_started:
        while len(waiters) < n_uploads:
            upload_started.wait(2)
            for w in waiters:
                w.set()

    assert done.wait(2)
