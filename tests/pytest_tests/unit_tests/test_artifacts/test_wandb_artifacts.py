import asyncio
import functools
import queue
import shutil
import unittest.mock as mock
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional
from unittest.mock import Mock

import pytest
import requests
from wandb.filesync.step_prepare import ResponsePrepare, StepPrepare
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.artifact_cache import artifact_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifacts_cache import ArtifactsCache
from wandb.sdk.artifacts.exceptions import ArtifactNotLoggedError
from wandb.sdk.artifacts.storage_policies.wandb_storage_policy import WandbStoragePolicy

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


def asyncify(f):
    """Convert a sync function to an async function. Useful for building mock async wrappers."""

    @functools.wraps(f)
    async def async_f(*args, **kwargs):
        return f(*args, **kwargs)

    return async_f


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
        birth_artifact_id=f"artifact-id-{name}",
        upload_url=f"http://wandb-test/upload-url-{name}",
        upload_headers=["x-my-header-key:my-header-val"],
        upload_id=None,
        storage_path="wandb_artifact/123456789",
        multipart_upload_urls=None,
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


def test_capped_cache():
    for i in range(101):
        art = Artifact(f"foo-{i}", type="test")
        art._id = f"foo-{i}"
        art._state = "COMMITTED"
        artifact_cache[art.id] = art
    assert len(artifact_cache) == 100


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
                store_file(WandbStoragePolicy(api=api), entry_local_path=example_file)
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
        upload_multipart_file_chunk_retry = Mock()
        complete_multipart_upload_artifact = Mock()
        upload_method = {
            "sync": upload_file_retry,
            "async": upload_file_retry_async,
        }[store_file_mode]

        return Mock(
            upload_file_retry=upload_file_retry,
            upload_file_retry_async=upload_file_retry_async,
            upload_method=upload_method,
            upload_multipart_file_chunk_retry=upload_multipart_file_chunk_retry,
            complete_multipart_upload_artifact=complete_multipart_upload_artifact,
        )

    def test_smoke(self, store_file: "StoreFileFixture", api, example_file: Path):
        store_file(WandbStoragePolicy(api=api), entry_local_path=example_file)
        api.upload_method.assert_called_once()

    def test_uploads_to_prepared_url(
        self, store_file: "StoreFileFixture", api, example_file: Path
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
            entry_local_path=example_file,
            preparer=preparer,
        )
        assert api.upload_method.call_args[0][0] == "https://wandb-test/dst"

    def test_passes_prepared_headers_to_upload(
        self, store_file: "StoreFileFixture", api, example_file: Path
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
            entry_local_path=example_file,
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
        example_file: Path,
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

        deduped = store_file(policy, entry_local_path=example_file, preparer=preparer)
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
        example_file: Path,
        has_local_path: bool,
        expect_upload: bool,
    ):
        policy = WandbStoragePolicy(api=api)

        deduped = store_file(
            policy,
            entry_local_path=example_file if has_local_path else None,
        )
        assert not deduped

        if expect_upload:
            api.upload_method.assert_called_once()
        else:
            api.upload_method.assert_not_called()

    @pytest.mark.parametrize("err", [None, Exception("some error")])
    def test_caches_result_on_success(
        self,
        store_file: "StoreFileFixture",
        api,
        example_file: Path,
        artifacts_cache: ArtifactsCache,
        err: Optional[Exception],
    ):
        size = example_file.stat().st_size

        api.upload_file_retry = Mock(side_effect=err)
        api.upload_file_retry_async = asyncify(Mock(side_effect=err))
        policy = WandbStoragePolicy(api=api, cache=artifacts_cache)

        assert not is_cache_hit(artifacts_cache, "my-digest", size)

        store = functools.partial(store_file, policy, entry_local_path=example_file)

        if err is None:
            store()
            assert is_cache_hit(artifacts_cache, "my-digest", size)
        else:
            with pytest.raises(Exception, match=err.args[0]):
                store()
            assert not is_cache_hit(artifacts_cache, "my-digest", size)

    @pytest.mark.parametrize(
        [
            "upload_url",
            "multipart_upload_urls",
            "expect_single_upload",
            "expect_multipart_upload",
            "expect_deduped",
        ],
        [
            (
                "http://wandb-test/dst",
                {
                    1: "http://wandb-test/part=1",
                    2: "http://wandb-test/part=2",
                    3: "http://wandb-test/part=3",
                },
                False,
                True,
                False,
            ),
            (
                None,
                {
                    1: "http://wandb-test/part=1",
                    2: "http://wandb-test/part=2",
                    3: "http://wandb-test/part=3",
                },
                False,
                False,
                True,
            ),  # super weird case but shouldn't happen, upload url should always be generated
            ("http://wandb-test/dst", None, True, False, False),
            (None, None, False, False, True),
        ],
    )
    @mock.patch(
        "wandb.sdk.artifacts.storage_policies.wandb_storage_policy.WandbStoragePolicy."
        "s3_multipart_file_upload"
    )
    def test_multipart_upload_handle_response(
        self,
        mock_s3_multipart_file_upload,
        api,
        example_file: Path,
        upload_url: Optional[str],
        multipart_upload_urls: Optional[dict],
        expect_multipart_upload: bool,
        expect_single_upload: bool,
        expect_deduped: bool,
    ):
        # Tests if we handle uploading correctly depending on what response we get from CreateArtifactFile.
        preparer = mock_preparer(
            prepare_sync=lambda spec: singleton_queue(
                dummy_response_prepare(spec)._replace(
                    upload_url=upload_url, multipart_upload_urls=multipart_upload_urls
                )
            )
        )
        policy = WandbStoragePolicy(api=api)
        # Mock minimum size for multipart so that we can test multipart
        with mock.patch(
            "wandb.sdk.artifacts.storage_policies.wandb_storage_policy."
            "S3_MIN_MULTI_UPLOAD_SIZE",
            example_file.stat().st_size,
        ):
            # We don't use the store_file fixture since multipart is not available in async
            deduped = self._store_file_sync(
                policy, entry_local_path=example_file, preparer=preparer
            )
            assert deduped == expect_deduped

            if expect_multipart_upload:
                mock_s3_multipart_file_upload.assert_called_once()
                api.complete_multipart_upload_artifact.assert_called_once()
                api.upload_file_retry.assert_not_called()
            elif expect_single_upload:
                api.upload_file_retry.assert_called_once()
                api.upload_multipart_file_chunk_retry.assert_not_called()
            else:
                api.upload_file_retry.assert_not_called()
                api.upload_multipart_file_chunk_retry.assert_not_called()

    def test_s3_multipart_file_upload(
        self,
        api,
        example_file: Path,
    ):
        # Tests that s3 multipart calls upload on every part and retrieves the etag for every part
        multipart_parts = {
            1: "http://wandb-test/part=1",
            2: "http://wandb-test/part=2",
            3: "http://wandb-test/part=3",
        }
        hex_digests = {1: "abc1", 2: "abc2", 3: "abc3"}
        chunk_size = 1
        policy = WandbStoragePolicy(api=api)
        responses = []
        for idx in range(1, len(hex_digests) + 1):
            etag_response = requests.Response()
            etag_response.headers = {"ETag": hex_digests[idx]}
            responses.append(etag_response)
        api.upload_multipart_file_chunk_retry.side_effect = responses

        with mock.patch("builtins.open", mock.mock_open(read_data="abc")):
            etags = policy.s3_multipart_file_upload(
                example_file, chunk_size, hex_digests, multipart_parts, extra_headers={}
            )
            assert api.upload_multipart_file_chunk_retry.call_count == 3
            # Note Etags == hex_digest when there isn't an additional encryption method for uploading.
            assert len(etags) == len(hex_digests)
            for etag in etags:
                assert etag["hexMD5"] == hex_digests[etag["partNumber"]]


@pytest.mark.parametrize("type", ["job", "wandb-history", "wandb-foo"])
def test_invalid_artifact_type(type):
    with pytest.raises(ValueError, match="reserved for internal use"):
        Artifact("foo", type=type)


@pytest.mark.parametrize(
    "property",
    [
        "entity",
        "project",
        "version",
        "source_entity",
        "source_project",
        "source_version",
        "ttl",
        "aliases",  # Perhaps shouldn't be restricted? It is today.
        "commit_hash",
        "file_count",  # Probably doesn't need to be restricted, but is today.
        "created_at",
        "updated_at",
    ],
)
def test_unlogged_artifact_property_errors(property):
    art = Artifact("foo", type="any")
    error_message = f"'Artifact.{property}' used prior to logging artifact"
    with pytest.raises(ArtifactNotLoggedError, match=error_message):
        getattr(art, property)


@pytest.mark.parametrize(
    "method",
    [
        "new_draft",
        "download",
        "checkout",
        "verify",
        "file",
        "files",
        "delete",
        "used_by",
        "logged_by",
        "json_encode",
    ],
)
def test_unlogged_artifact_basic_method_errors(method):
    art = Artifact("foo", type="any")
    error_message = f"'Artifact.{method}' used prior to logging artifact"
    with pytest.raises(ArtifactNotLoggedError, match=error_message):
        getattr(art, method)()


def test_unlogged_artifact_other_method_errors():
    art = Artifact("foo", type="any")
    with pytest.raises(ArtifactNotLoggedError, match="Artifact.get_entry"):
        art.get_entry("pathname")

    with pytest.raises(ArtifactNotLoggedError, match="Artifact.get"):
        art["obj_name"]


def test_cache_write_failure_is_ignored(monkeypatch, capsys):
    def bad_write(*args, **kwargs):
        raise FileNotFoundError("unable to copy from source file")

    monkeypatch.setattr(shutil, "copyfileobj", bad_write)
    policy = WandbStoragePolicy()
    path = Path("foo.txt")
    path.write_text("hello")

    entry = ArtifactManifestEntry(
        path=str(path),
        digest="NWQ0MTQwMmFiYzRiMmE3NmI5NzE5ZDkxMTAxN2M1OTI=",
        local_path=str(path),
        size=path.stat().st_size,
    )

    policy._write_cache(entry)

    captured = capsys.readouterr()
    assert "Failed to cache" in captured.err


def test_artifact_manifest_length():
    artifact = Artifact("test-artifact", "test-type")
    assert len(artifact.manifest) == 0
    with artifact.new_file("test.txt") as f:
        f.write("test")
    assert len(artifact.manifest) == 1

    testpath = Path("test.txt")
    testpath.write_text("also a test")
    artifact.add_reference(testpath.resolve().as_uri(), "test2.txt")
    assert len(artifact.manifest) == 2
