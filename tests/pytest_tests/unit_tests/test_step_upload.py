import asyncio
import concurrent.futures
import functools
import queue
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, MutableSequence, Optional
from unittest.mock import DEFAULT, Mock, patch

import pytest
from wandb.filesync import stats
from wandb.filesync.step_upload import (
    Event,
    RequestCommitArtifact,
    RequestFinish,
    RequestUpload,
    StepUpload,
)
from wandb.sdk.internal import file_stream, internal_api
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.wandb_settings import Settings


def asyncify(f):
    """Convert a sync function to an async function. Useful for building mock async wrappers."""

    @functools.wraps(f)
    async def async_f(*args, **kwargs):
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: f(*args, **kwargs)
        )

    return async_f


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


def get_upload_url(save_name: str):
    return mock_upload_urls("my-proj", [save_name])[2][save_name]["url"]


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
            "api": make_api(),
            "stats": Mock(spec=stats.Stats),
            "event_queue": queue.Queue(),
            "max_threads": 10,
            "file_stream": Mock(spec=file_stream.FileStreamApi),
            **kwargs,
        }
    )


def make_request_upload(path: Path, **kwargs: Any) -> RequestUpload:
    if "save_fn" in kwargs:
        # We want a lot of tests to run against both sync and async
        # upload implementations. For convenience, we let tests
        # specify only a sync save_fn, and we generate an equivalent
        # save_fn_async, so they can run against both.
        kwargs.setdefault("save_fn_async", asyncify(kwargs["save_fn"]))

    return RequestUpload(
        path=str(path),
        **{
            "save_name": str(path),
            "artifact_id": None,
            "md5": None,
            "copied": False,
            "save_fn": None,
            "save_fn_async": None,
            "digest": None,
            **kwargs,
        },
    )


def make_request_commit(artifact_id: str, **kwargs: Any) -> RequestCommitArtifact:
    return RequestCommitArtifact(
        artifact_id=artifact_id,
        **{
            "before_commit": lambda: None,
            "result_future": concurrent.futures.Future(),
            "finalize": True,
            **kwargs,
        },
    )


def make_api(**kwargs: Any) -> Mock:
    return Mock(
        spec=internal_api.Api,
        **{
            "upload_urls": Mock(wraps=mock_upload_urls),
            "upload_file_retry": Mock(wraps=mock_upload_file_retry),
            **kwargs,
        },
    )


def make_async_settings(concurrency_limit: Optional[int]) -> SettingsStatic:
    return SettingsStatic(
        Settings(_async_upload_concurrency_limit=concurrency_limit).make_static()
    )


def finish_and_wait(command_queue: queue.Queue):
    done = threading.Event()
    command_queue.put(RequestFinish(callback=done.set))
    assert done.wait(2)


class UploadBlockingMockApi(Mock):
    def __init__(self, *args, **kwargs):
        kwargs = {
            **dict(
                upload_urls=Mock(wraps=mock_upload_urls),
                upload_file_retry=Mock(wraps=self._mock_upload),
                upload_file_retry_async=Mock(wraps=self._mock_upload_async),
            ),
            **kwargs,
        }

        super().__init__(
            *args,
            **kwargs,
        )

        self.mock_upload_file_waiters: MutableSequence[Callable[[], None]] = []
        self.mock_upload_started = threading.Condition()

    def wait_for_upload(self, timeout: float) -> Optional[Callable[[], None]]:
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
            self.mock_upload_file_waiters.append(ev.set)
            self.mock_upload_started.notify_all()
        ev.wait()

    async def _mock_upload_async(self, *args, **kwargs):
        ev = asyncio.Event()
        loop = asyncio.get_event_loop()
        with self.mock_upload_started:
            self.mock_upload_file_waiters.append(
                functools.partial(loop.call_soon_threadsafe, ev.set)
            )
            self.mock_upload_started.notify_all()
        await ev.wait()


def run_step_upload(
    commands: Iterable[Event],
    **step_upload_kwargs: Any,
):
    q = queue.Queue()
    for cmd in commands:
        q.put(cmd)
    step_upload = make_step_upload(
        event_queue=q,
        **step_upload_kwargs,
    )
    step_upload.start()

    finish_and_wait(q)


class TestFinish:
    def test_finishes_when_no_commands(self):
        run_step_upload([])

    def test_finishes_after_simple_upload(self):
        api = make_api()
        run_step_upload([make_request_upload(make_tmp_file(Path("/tmp")))], api=api)
        api.upload_file_retry.assert_called()

    def test_finishes_after_nonexistent_upload_failure(self, tmp_path: Path):
        api = make_api()
        run_step_upload(
            [make_request_upload(tmp_path / "nonexistent-file.txt")], api=api
        )
        api.upload_file_retry.assert_not_called()

    def test_finishes_after_multiple_uploads(self, tmp_path: Path):
        api = make_api()
        run_step_upload(
            [
                make_request_upload(make_tmp_file(tmp_path)),
                make_request_upload(make_tmp_file(tmp_path)),
                make_request_upload(make_tmp_file(tmp_path)),
            ],
            api=api,
        )
        api.upload_file_retry.assert_called()

    def test_finishes_after_upload_urls_err(self, tmp_path: Path):
        api = make_api(upload_urls=Mock(side_effect=Exception("upload_urls failed")))
        run_step_upload([make_request_upload(make_tmp_file(tmp_path))], api=api)
        api.upload_urls.assert_called()

    def test_finishes_after_upload_err(self, tmp_path: Path):
        api = make_api(upload_file_retry=Mock(side_effect=Exception("upload failed")))
        run_step_upload([make_request_upload(make_tmp_file(tmp_path))], api=api)
        api.upload_file_retry.assert_called()

    def test_finishes_after_artifact_upload_err(self, tmp_path: Path):
        api = make_api(upload_file_retry=Mock(side_effect=Exception("upload failed")))
        run_step_upload(
            [
                make_request_upload(make_tmp_file(tmp_path), artifact_id="my-artifact"),
                make_request_commit("my-artifact"),
            ],
            api=api,
        )
        api.upload_file_retry.assert_called()

    def test_finishes_after_artifact_commit(self, tmp_path: Path):
        api = make_api()
        run_step_upload(
            [
                make_request_upload(make_tmp_file(tmp_path), artifact_id="my-artifact"),
                make_request_commit("my-artifact"),
            ],
            api=api,
        )
        api.commit_artifact.assert_called()

    def test_finishes_after_artifact_commit_err(self, tmp_path: Path):
        api = make_api(commit_artifact=Mock(side_effect=Exception("commit failed")))
        run_step_upload(
            [
                make_request_upload(make_tmp_file(tmp_path), artifact_id="my-artifact"),
                make_request_commit("my-artifact"),
            ],
            api=api,
        )
        api.commit_artifact.assert_called()

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
        unblock()
        assert done.wait(2)


class TestUpload:
    @pytest.fixture(params=[None, 100])
    def async_settings(self, request) -> SettingsStatic:
        """Tests that use this fixture run twice: with async uploads enabled/disabled.

        Most tests in this class should use this fixture.
        """
        return make_async_settings(request.param)

    def test_upload(
        self,
        tmp_path: Path,
        async_settings: SettingsStatic,
    ):
        api = make_api()
        cmd = make_request_upload(make_tmp_file(tmp_path))

        run_step_upload(
            [cmd],
            api=api,
            settings=async_settings,
        )

        api.upload_file_retry.assert_called_once()
        assert api.upload_file_retry.call_args[0][0] == get_upload_url(cmd.save_name)

    def test_reuploads_if_event_during_upload(
        self,
        tmp_path: Path,
        async_settings: SettingsStatic,
    ):
        f = make_tmp_file(tmp_path)

        api = UploadBlockingMockApi()

        q = queue.Queue()
        q.put(make_request_upload(f))

        step_upload = make_step_upload(api=api, event_queue=q, settings=async_settings)
        step_upload.start()

        unblock = api.wait_for_upload(2)
        q.put(make_request_upload(f))
        # TODO(spencerpearson): if we RequestUpload _several_ more times,
        # it seems like we should still only reupload once?
        # But as of 2022-12-15, the behavior is to reupload several more times,
        # the not-yet-actionable requests not being deduped against each other.

        time.sleep(0.1)  # TODO: better way to wait for the message to be processed
        assert api.upload_file_retry.call_count == 1
        unblock()

        unblock = api.wait_for_upload(2)
        assert unblock
        unblock()

        finish_and_wait(q)
        assert api.upload_file_retry.call_count == 2

    @pytest.mark.parametrize("copied", [True, False])
    def test_deletes_after_upload_iff_copied(
        self,
        tmp_path: Path,
        copied: bool,
        async_settings: SettingsStatic,
    ):
        f = make_tmp_file(tmp_path)

        api = UploadBlockingMockApi()

        q = queue.Queue()
        q.put(make_request_upload(f, copied=copied))

        step_upload = make_step_upload(api=api, event_queue=q, settings=async_settings)
        step_upload.start()

        unblock = api.wait_for_upload(2)
        assert f.exists()

        unblock()

        finish_and_wait(q)

        if copied:
            assert not f.exists()
        else:
            assert f.exists()

    class TestErrorDoesntStopFutureUploads:
        def test_nonexistent_file_upload(
            self,
            tmp_path: Path,
            async_settings: SettingsStatic,
        ):
            api = make_api()
            good_cmd = make_request_upload(make_tmp_file(tmp_path))
            run_step_upload(
                [
                    make_request_upload(tmp_path / "nonexistent-file.txt"),
                    good_cmd,
                ],
                api=api,
                settings=async_settings,
                max_threads=1,
            )
            good_url = get_upload_url(good_cmd.save_name)
            assert api.upload_file_retry.call_args[0][0] == good_url

        def test_upload_urls_err(
            self,
            tmp_path: Path,
            async_settings: SettingsStatic,
        ):
            api = make_api(
                upload_urls=Mock(
                    wraps=mock_upload_urls,
                    side_effect=[Exception("upload_urls failed"), DEFAULT],
                )
            )
            good_cmd = make_request_upload(make_tmp_file(tmp_path))
            run_step_upload(
                [
                    make_request_upload(make_tmp_file(tmp_path)),
                    good_cmd,
                ],
                api=api,
                settings=async_settings,
                max_threads=1,
            )
            good_url = get_upload_url(good_cmd.save_name)
            assert api.upload_file_retry.call_args[0][0] == good_url

        def test_upload_file_retry_err(
            self,
            tmp_path: Path,
            async_settings: SettingsStatic,
        ):
            api = make_api(
                upload_file_retry=Mock(
                    wraps=mock_upload_file_retry,
                    side_effect=[Exception("upload_file_retry failed"), DEFAULT],
                ),
            )
            good_cmd = make_request_upload(make_tmp_file(tmp_path))
            run_step_upload(
                [
                    make_request_upload(make_tmp_file(tmp_path)),
                    good_cmd,
                ],
                api=api,
                settings=async_settings,
                max_threads=1,
            )
            good_url = get_upload_url(good_cmd.save_name)
            assert api.upload_file_retry.call_args[0][0] == good_url

        def test_save_fn_err(
            self,
            tmp_path: Path,
            async_settings: SettingsStatic,
        ):
            api = make_api()
            good_cmd = make_request_upload(make_tmp_file(tmp_path))
            run_step_upload(
                [
                    make_request_upload(
                        make_tmp_file(tmp_path),
                        save_fn=Mock(side_effect=Exception("save_fn failed")),
                    ),
                    good_cmd,
                ],
                api=api,
                settings=async_settings,
                max_threads=1,
            )
            good_url = get_upload_url(good_cmd.save_name)
            assert api.upload_file_retry.call_args[0][0] == good_url

    class TestStats:
        def test_updates_on_read_without_save_fn(
            self,
            tmp_path: Path,
            async_settings: SettingsStatic,
        ):
            f = make_tmp_file(tmp_path)
            mock_stats = Mock(spec=stats.Stats)

            run_step_upload(
                [make_request_upload(f)], settings=async_settings, stats=mock_stats
            )

            mock_stats.update_uploaded_file.assert_called_with(str(f), f.stat().st_size)

        def test_updates_on_read_with_save_fn(
            self,
            tmp_path: Path,
            async_settings: SettingsStatic,
        ):
            f = make_tmp_file(tmp_path)
            size = f.stat().st_size
            mock_stats = Mock(spec=stats.Stats)

            run_step_upload(
                [make_request_upload(f, save_fn=lambda progress: progress(size, size))],
                settings=async_settings,
                stats=mock_stats,
            )

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
            async_settings: SettingsStatic,
        ):
            f = make_tmp_file(tmp_path)

            api = make_api(
                upload_file_retry=Mock(
                    side_effect=Exception("upload_file_retry failed")
                ),
            )

            mock_stats = Mock(spec=stats.Stats)
            run_step_upload(
                [make_request_upload(f, save_fn=save_fn)],
                api=api,
                settings=async_settings,
                stats=mock_stats,
            )

            mock_stats.update_failed_file.assert_called_once_with(str(f))

        @pytest.mark.parametrize("deduped", [True, False])
        def test_update_on_deduped(
            self,
            tmp_path: Path,
            deduped: bool,
            async_settings: SettingsStatic,
        ):
            f = make_tmp_file(tmp_path)
            mock_stats = Mock(spec=stats.Stats)

            run_step_upload(
                [make_request_upload(f, save_fn=Mock(return_value=deduped))],
                settings=async_settings,
                stats=mock_stats,
            )

            if deduped:
                mock_stats.set_file_deduped.assert_called_once_with(str(f))
            else:
                mock_stats.set_file_deduped.assert_not_called()

    class TestNotifiesFileStreamOnSuccess:
        class TestWithoutSaveFn:
            def test_notifies_on_success(
                self,
                tmp_path: Path,
                async_settings: SettingsStatic,
            ):
                api = make_api()
                cmd = make_request_upload(make_tmp_file(tmp_path))
                mock_file_stream = Mock(spec=file_stream.FileStreamApi)

                run_step_upload(
                    [cmd],
                    api=api,
                    settings=async_settings,
                    file_stream=mock_file_stream,
                )

                mock_file_stream.push_success.assert_called_once_with(
                    cmd.artifact_id, cmd.save_name
                )

            def test_no_notify_on_upload_urls_err(
                self,
                tmp_path: Path,
                async_settings: SettingsStatic,
            ):
                api = make_api(upload_urls=Mock(side_effect=Exception()))
                cmd = make_request_upload(make_tmp_file(tmp_path))
                mock_file_stream = Mock(spec=file_stream.FileStreamApi)

                run_step_upload(
                    [cmd],
                    api=api,
                    settings=async_settings,
                    file_stream=mock_file_stream,
                )

                api.upload_urls.assert_called_once()
                mock_file_stream.push_success.assert_not_called()

            def test_no_notify_on_upload_file_err(
                self,
                tmp_path: Path,
                async_settings: SettingsStatic,
            ):
                api = make_api(upload_file_retry=Mock(side_effect=Exception()))
                cmd = make_request_upload(make_tmp_file(tmp_path))
                mock_file_stream = Mock(spec=file_stream.FileStreamApi)

                run_step_upload(
                    [cmd],
                    api=api,
                    settings=async_settings,
                    file_stream=mock_file_stream,
                )

                api.upload_file_retry.assert_called_once()
                mock_file_stream.push_success.assert_not_called()

        class TestWithSaveFn:
            @pytest.mark.parametrize(
                "deduped",
                [True, False],
            )
            def test_notifies_on_success(
                self,
                tmp_path: Path,
                deduped: bool,
                async_settings: SettingsStatic,
            ):
                cmd = make_request_upload(
                    make_tmp_file(tmp_path), save_fn=Mock(return_value=deduped)
                )
                mock_file_stream = Mock(spec=file_stream.FileStreamApi)

                run_step_upload(
                    [cmd], settings=async_settings, file_stream=mock_file_stream
                )

                mock_file_stream.push_success.assert_called_once_with(
                    cmd.artifact_id, cmd.save_name
                )

            def test_no_notify_on_err(
                self,
                tmp_path: Path,
                async_settings: SettingsStatic,
            ):
                cmd = make_request_upload(
                    make_tmp_file(tmp_path), save_fn=Mock(side_effect=Exception())
                )
                mock_file_stream = Mock(spec=file_stream.FileStreamApi)

                run_step_upload(
                    [cmd], settings=async_settings, file_stream=mock_file_stream
                )

                mock_file_stream.push_success.assert_not_called()

    def test_uses_save_fn_async_iff_settings_say_to(
        self,
        tmp_path: Path,
        async_settings: SettingsStatic,
    ):
        save_fn_sync = Mock(return_value=False)
        save_fn_async = Mock(wraps=asyncify(Mock(return_value=False)))

        api = make_api()

        run_step_upload(
            [
                make_request_upload(
                    make_tmp_file(tmp_path),
                    save_fn=save_fn_sync,
                    save_fn_async=save_fn_async,
                )
            ],
            api=api,
            settings=async_settings,
        )

        if async_settings._async_upload_concurrency_limit:
            save_fn_async.assert_called_once()
            save_fn_sync.assert_not_called()
        else:
            save_fn_sync.assert_called_once()
            save_fn_async.assert_not_called()

        # The upload should go through `save_fn` and `save_fn_async` (which are noops),
        # not calling API methods directly:
        api.upload_file.assert_not_called()
        api.upload_file_async.assert_not_called()
        api.upload_file_retry.assert_not_called()
        api.upload_file_retry_async.assert_not_called()

    def test_no_async_if_no_save_fn(
        self,
        tmp_path: Path,
        async_settings: SettingsStatic,
    ):
        api = make_api()

        run_step_upload(
            [make_request_upload(make_tmp_file(tmp_path))],
            api=api,
            settings=async_settings,
        )

        # These uploads should go through `upload_file_retry`, not anything async (for now):
        api.upload_file_retry.assert_called()
        api.upload_file_async.assert_not_called()
        api.upload_file_retry_async.assert_not_called()


class TestAsyncUpload:
    def test_falls_back_to_sync_on_error(self, tmp_path: Path):
        save_fn_sync = Mock(return_value=False)
        save_fn_async = Mock(
            wraps=asyncify(Mock(side_effect=Exception("Async upload failed")))
        )

        run_step_upload(
            [
                make_request_upload(
                    make_tmp_file(tmp_path),
                    save_fn=save_fn_sync,
                    save_fn_async=save_fn_async,
                )
            ],
            settings=make_async_settings(10),
        )

        save_fn_async.assert_called_once()
        save_fn_sync.assert_called_once()

    @patch("wandb._sentry.exception")
    def test_reports_err_to_sentry(self, exception: Mock, tmp_path: Path):
        exc = Exception("Async upload failed")
        save_fn_async = Mock(wraps=asyncify(Mock(side_effect=exc)))

        run_step_upload(
            [
                make_request_upload(
                    make_tmp_file(tmp_path),
                    save_fn=Mock(return_value=False),
                    save_fn_async=save_fn_async,
                )
            ],
            settings=make_async_settings(10),
        )

        exception.assert_called_once_with(exc)


class TestArtifactCommit:
    @pytest.mark.parametrize(
        ["finalize"],
        [(True,), (False,)],
    )
    def test_commits_iff_finalize(
        self,
        finalize: bool,
    ):
        api = make_api()

        run_step_upload([make_request_commit("my-art", finalize=finalize)], api=api)

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

        unblock()
        finish_and_wait(q)
        api.commit_artifact.assert_called_once()

    def test_no_commit_if_upload_fails(
        self,
        tmp_path: Path,
    ):
        api = make_api(upload_file_retry=Mock(side_effect=Exception("upload failed")))

        run_step_upload(
            [
                make_request_upload(make_tmp_file(tmp_path), artifact_id="my-art"),
                make_request_commit("my-art"),
            ],
            api=api,
        )

        api.commit_artifact.assert_not_called()

    def test_calls_before_commit_hook(self):
        events = []
        api = make_api(commit_artifact=lambda *args, **kwargs: events.append("commit"))

        run_step_upload(
            [
                make_request_commit(
                    "my-art",
                    before_commit=lambda: events.append("before"),
                    finalize=True,
                )
            ],
            api=api,
        )

        assert events == ["before", "commit"]

    class TestAlwaysResolvesFut:
        def test_success(self):
            future = concurrent.futures.Future()

            run_step_upload(
                [make_request_commit("my-art", result_future=future)],
            )

            assert future.done() and future.exception() is None

        def test_upload_fails(self, tmp_path: Path):
            exc = Exception("upload_file_retry failed")
            api = make_api(upload_file_retry=Mock(side_effect=exc))

            future = concurrent.futures.Future()

            run_step_upload(
                [
                    make_request_upload(make_tmp_file(tmp_path), artifact_id="my-art"),
                    make_request_commit("my-art", result_future=future),
                ],
                api=api,
            )

            assert future.done() and future.exception() == exc

        def test_before_commit_hook_fails(self):
            future = concurrent.futures.Future()

            exc = Exception("upload_file_retry failed")

            run_step_upload(
                [
                    make_request_commit(
                        "my-art",
                        before_commit=Mock(side_effect=exc),
                        result_future=future,
                    )
                ]
            )

            assert future.done() and future.exception() == exc

        def test_commit_fails(self):
            exc = Exception("commit failed")
            api = make_api(commit_artifact=Mock(side_effect=exc))

            future = concurrent.futures.Future()

            run_step_upload(
                [make_request_commit("my-art", result_future=future)],
                api=api,
            )

            assert future.done() and future.exception() == exc


@pytest.mark.parametrize("is_async", [True, False])
def test_enforces_concurrency_limit(tmp_path: Path, is_async: bool):
    concurrency_limit = 3

    q = queue.Queue()

    api = UploadBlockingMockApi()

    def save_fn_sync(path: Path, *args, **kwargs):
        api.upload_file_retry(f"http://dst/{path}", path.open("rb"))

    async def save_fn_async(path: Path, *args, **kwargs):
        await api.upload_file_retry_async(f"http://dst/{path}", path.open("rb"))

    def add_job():
        path = make_tmp_file(tmp_path)
        q.put(
            make_request_upload(
                path,
                save_fn=(
                    Mock(
                        side_effect=Exception(
                            "save_fn should not be called in async test"
                        )
                    )
                    if is_async
                    else functools.partial(save_fn_sync, path)
                ),
                save_fn_async=(
                    functools.partial(save_fn_async, path)
                    if is_async
                    else Mock(
                        side_effect=Exception(
                            "save_fn_async should not be called in sync test"
                        )
                    )
                ),
            )
        )

    step_upload = make_step_upload(
        api=api,
        event_queue=q,
        max_threads=(concurrency_limit + 10) if is_async else concurrency_limit,
        settings=make_async_settings(
            concurrency_limit=concurrency_limit if is_async else None
        ),
    )
    step_upload.start()

    waiters = []

    # first few jobs should start without blocking
    for _ in range(concurrency_limit):
        add_job()
        waiters.append(api.wait_for_upload(0.1))

    # next job should block...
    add_job()
    assert not api.wait_for_upload(0.1)

    # ...until we release one of the first jobs
    waiters.pop()()
    waiters.append(api.wait_for_upload(0.1))

    # let all jobs finish, to release the threads
    for w in waiters:
        w()

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

    unblock()
    assert done.wait(2)
    step_upload._thread.join(timeout=0.1)
    assert not step_upload.is_alive()
