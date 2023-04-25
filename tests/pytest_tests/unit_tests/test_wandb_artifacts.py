import asyncio
import functools
import queue
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional
from unittest.mock import Mock

import pytest
from wandb.filesync.step_prepare import ResponsePrepare, StepPrepare
from wandb.sdk.wandb_artifacts import (
    Artifact,
    ArtifactManifestEntry,
    ArtifactsCache,
    WandbStoragePolicy,
)

if TYPE_CHECKING:
    import sys

    from wandb.sdk.internal.internal_api import CreateArtifactFileSpecInput

    if sys.version_info >= (3, 8):
        from typing import Protocol
    else:
        from typing_extensions import Protocol

    class StoreFileFixture(Protocol):
        def __call__(
            self,
            policy: WandbStoragePolicy,
            artifact_id: str,
            artifact_manifest_id: str,
            entry_path: str,
            entry_digest: str,
            entry_local_path: Optional[Path] = None,
            preparer: Optional[StepPrepare] = None,
        ) -> bool:
            pass


@pytest.fixture
def artifacts_cache(tmp_path: Path) -> ArtifactsCache:
    return ArtifactsCache(tmp_path / "artifacts-cache")


def asyncify(f):
    """Convert a sync function to an async function. Useful for building mock async wrappers."""

    @functools.wraps(f)
    async def async_f(*args, **kwargs):
        return f(*args, **kwargs)

    return async_f


def some_file(tmp_path: Path) -> Path:
    f = tmp_path / "some-file"
    f.write_text("some-content")
    return f


def is_cache_hit(cache: ArtifactsCache, digest: str, size: int) -> bool:
    _, hit, _ = cache.check_md5_obj_path(digest, size)
    return hit


def singleton_queue(x):
    q = queue.Queue()
    q.put(x)
    return q


def dummy_response_prepare(spec):
    name = spec["name"]
    return ResponsePrepare(
        upload_url=f"http://wandb-test/upload-url-{name}",
        upload_headers=["x-my-header-key:my-header-val"],
        birth_artifact_id=f"artifact-id-{name}",
    )


def mock_prepare_sync_to_async(sync):
    def mock_prepare_async(*args, **kwargs):
        q = sync(*args, **kwargs)
        return asyncio.get_event_loop().run_in_executor(None, q.get)

    return mock_prepare_async


def mock_prepare_sync(
    spec: "CreateArtifactFileSpecInput",
) -> ResponsePrepare:
    return singleton_queue(dummy_response_prepare(spec))


def mock_preparer(**kwargs):
    kwargs.setdefault("prepare_sync", Mock(wraps=mock_prepare_sync))
    kwargs.setdefault(
        "prepare_async", Mock(wraps=mock_prepare_sync_to_async(kwargs["prepare_sync"]))
    )
    return Mock(**kwargs)


class TestStoreFile:
    @staticmethod
    def _fixture_kwargs_to_kwargs(
        artifact_id: str = "my-artifact-id",
        artifact_manifest_id: str = "my-artifact-manifest-id",
        entry_path: str = "my-path",
        entry_digest: str = "my-digest",
        entry_local_path: Optional[Path] = None,
        preparer: Optional[StepPrepare] = None,
    ) -> Mapping[str, Any]:
        if preparer is None:
            preparer = mock_preparer()
        return dict(
            artifact_id=artifact_id,
            artifact_manifest_id=artifact_manifest_id,
            entry=ArtifactManifestEntry(
                path=entry_path,
                digest=entry_digest,
                local_path=str(entry_local_path) if entry_local_path else None,
                size=entry_local_path.stat().st_size if entry_local_path else None,
            ),
            preparer=preparer if preparer else mock_preparer(),
        )

    @staticmethod
    def _store_file_sync(policy: WandbStoragePolicy, **kwargs) -> bool:
        """Runs store_file_sync to completion.

        Don't call this directly; use the `store_file` fixture instead, to ensure that
        whatever logic you're testing works with both sync and async impls.

        If you're writing a test that only cares about the sync impl, you should
        probably just call `policy.store_file_sync` directly.
        """
        return policy.store_file_sync(
            **TestStoreFile._fixture_kwargs_to_kwargs(**kwargs)
        )

    @staticmethod
    def _store_file_async(policy: WandbStoragePolicy, **kwargs) -> bool:
        """Runs store_file_async to completion.

        Don't call this directly; use the `store_file` fixture instead, to ensure that
        whatever logic you're testing works with both sync and async impls.

        If you're writing a test that only cares about the async impl, you should
        probably just call `policy.store_file_async` directly.
        """
        return asyncio.new_event_loop().run_until_complete(
            policy.store_file_async(**TestStoreFile._fixture_kwargs_to_kwargs(**kwargs))
        )

    @pytest.fixture(params=["sync", "async"])
    def store_file_mode(self, request) -> str:
        return request.param

    @pytest.fixture
    def store_file(self, store_file_mode: str) -> "StoreFileFixture":
        """Fixture to run either prepare_sync or prepare_async and return the result.

        Tests that use this fixture will run twice: once where it uses the sync impl,
        and once where it uses the async impl. This ensures that whatever logic you're
        testing works with both sync and async impls.

        Example usage:

            def test_smoke(store_file: "StoreFileFixture", api):
                store_file(WandbStoragePolicy(api=api), entry_local_path=some_file(tmp_path))
                api.upload_method.assert_called_once()
        """
        if store_file_mode == "sync":
            return TestStoreFile._store_file_sync
        elif store_file_mode == "async":
            return TestStoreFile._store_file_async
        else:
            raise ValueError(f"Unknown store_file mode: {store_file_mode}")

    @pytest.fixture
    def api(self, store_file_mode):
        """Fixture to give a mock `internal_api.Api` object, with properly-functioning sync/async upload methods.

        Also adds an `upload_method` field, which points to either `upload_file_retry`
        or `upload_file_retry_async`, depending on which `store_file_mode` is being used.
        This is useful for making assertions about what files `store_file` uploaded,
        without needing to know whether it used the sync or async impl.
        """
        upload_file_retry = Mock()
        upload_file_retry_async = Mock(wraps=asyncify(Mock()))
        upload_method = {
            "sync": upload_file_retry,
            "async": upload_file_retry_async,
        }[store_file_mode]

        return Mock(
            upload_file_retry=upload_file_retry,
            upload_file_retry_async=upload_file_retry_async,
            upload_method=upload_method,
        )

    def test_smoke(self, store_file: "StoreFileFixture", api, tmp_path: Path):
        store_file(WandbStoragePolicy(api=api), entry_local_path=some_file(tmp_path))
        api.upload_method.assert_called_once()

    def test_uploads_to_prepared_url(
        self, store_file: "StoreFileFixture", api, tmp_path: Path
    ):
        preparer = mock_preparer(
            prepare_sync=lambda spec: singleton_queue(
                dummy_response_prepare(spec)._replace(
                    upload_url="https://wandb-test/dst"
                )
            )
        )
        store_file(
            WandbStoragePolicy(api=api),
            entry_local_path=some_file(tmp_path),
            preparer=preparer,
        )
        assert api.upload_method.call_args[0][0] == "https://wandb-test/dst"

    def test_passes_prepared_headers_to_upload(
        self, store_file: "StoreFileFixture", api, tmp_path: Path
    ):
        preparer = mock_preparer(
            prepare_sync=lambda spec: singleton_queue(
                dummy_response_prepare(spec)._replace(
                    upload_headers=["x-my-header:my-header-val"]
                )
            )
        )
        store_file(
            WandbStoragePolicy(api=api),
            entry_local_path=some_file(tmp_path),
            preparer=preparer,
        )
        assert api.upload_method.call_args[1]["extra_headers"] == {
            "x-my-header": "my-header-val"
        }

    @pytest.mark.parametrize(
        ["upload_url", "expect_upload", "expect_deduped"],
        [
            ("http://wandb-test/dst", True, False),
            (None, False, True),
        ],
    )
    def test_skips_upload_if_no_prepared_url(
        self,
        store_file: "StoreFileFixture",
        api,
        tmp_path: Path,
        upload_url: Optional[str],
        expect_upload: bool,
        expect_deduped: bool,
    ):
        preparer = mock_preparer(
            prepare_sync=lambda spec: singleton_queue(
                dummy_response_prepare(spec)._replace(upload_url=upload_url)
            )
        )
        policy = WandbStoragePolicy(api=api)

        deduped = store_file(
            policy, entry_local_path=some_file(tmp_path), preparer=preparer
        )
        assert deduped == expect_deduped

        if expect_upload:
            api.upload_method.assert_called_once()
        else:
            api.upload_method.assert_not_called()

    @pytest.mark.parametrize(
        ["has_local_path", "expect_upload"],
        [
            (True, True),
            (False, False),
        ],
    )
    def test_skips_upload_if_no_local_path(
        self,
        store_file: "StoreFileFixture",
        api,
        tmp_path: Path,
        has_local_path: bool,
        expect_upload: bool,
    ):
        policy = WandbStoragePolicy(api=api)

        deduped = store_file(
            policy,
            entry_local_path=some_file(tmp_path) if has_local_path else None,
        )
        assert not deduped

        if expect_upload:
            api.upload_method.assert_called_once()
        else:
            api.upload_method.assert_not_called()

    @pytest.mark.parametrize(
        "err",
        [
            None,
            Exception("some error"),
        ],
    )
    def test_caches_result_on_success(
        self,
        store_file: "StoreFileFixture",
        api,
        tmp_path: Path,
        artifacts_cache: ArtifactsCache,
        err: Optional[Exception],
    ):
        f = some_file(tmp_path)

        api.upload_file_retry = Mock(side_effect=err)
        api.upload_file_retry_async = asyncify(Mock(side_effect=err))
        policy = WandbStoragePolicy(api=api, cache=artifacts_cache)

        assert not is_cache_hit(artifacts_cache, "my-digest", f.stat().st_size)

        store = functools.partial(store_file, policy, entry_local_path=f)

        if err is None:
            store()
            assert is_cache_hit(artifacts_cache, "my-digest", f.stat().st_size)
        else:
            with pytest.raises(Exception, match=err.args[0]):
                store()
            assert not is_cache_hit(artifacts_cache, "my-digest", f.stat().st_size)


@pytest.mark.parametrize("type", ["job", "wandb-history", "wandb-foo"])
def test_invalid_artifact_type(type):
    with pytest.raises(ValueError, match="reserved for internal use"):
        Artifact("foo", type=type)
