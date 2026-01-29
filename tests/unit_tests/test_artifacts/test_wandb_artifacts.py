import functools
import queue
import shutil
import unittest.mock as mock
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from string import ascii_letters, digits
from typing import TYPE_CHECKING, Any, Mapping, Optional
from unittest.mock import Mock

import pytest
import requests
import responses
from hypothesis import given
from hypothesis.strategies import from_regex, text
from wandb.filesync.step_prepare import ResponsePrepare, StepPrepare
from wandb.sdk.artifacts._validators import NAME_MAXLEN
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.artifact_file_cache import ArtifactFileCache
from wandb.sdk.artifacts.artifact_instance_cache import artifact_instance_cache
from wandb.sdk.artifacts.artifact_manifest_entry import ArtifactManifestEntry
from wandb.sdk.artifacts.artifact_state import ArtifactState
from wandb.sdk.artifacts.exceptions import ArtifactNotLoggedError
from wandb.sdk.artifacts.storage_policies._multipart import (
    multipart_download,
    should_multipart_download,
)
from wandb.sdk.artifacts.storage_policies._url_provider import SharedUrlProvider
from wandb.sdk.artifacts.storage_policies.wandb_storage_policy import WandbStoragePolicy

if TYPE_CHECKING:
    from typing import Protocol

    from wandb.sdk.internal.internal_api import CreateArtifactFileSpecInput

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


def is_cache_hit(cache: ArtifactFileCache, digest: str, size: int) -> bool:
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


def mock_prepare(spec: "CreateArtifactFileSpecInput") -> ResponsePrepare:
    return singleton_queue(dummy_response_prepare(spec))


def mock_preparer(**kwargs):
    kwargs.setdefault("prepare", Mock(wraps=mock_prepare))
    return Mock(**kwargs)


def test_capped_cache():
    for i in range(101):
        art = Artifact(f"foo-{i}", type="test")
        art._id = f"foo-{i}"
        art._state = "COMMITTED"
        artifact_instance_cache[art.id] = art
    assert len(artifact_instance_cache) == 100


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
                local_path=entry_local_path,
            ),
            preparer=preparer if preparer else mock_preparer(),
        )

    @staticmethod
    def _store_file(policy: WandbStoragePolicy, **kwargs) -> bool:
        """Runs store_file to completion."""
        return policy.store_file(**TestStoreFile._fixture_kwargs_to_kwargs(**kwargs))

    @pytest.fixture(params=["sync", "async"])
    def store_file_mode(self, request) -> str:
        return request.param

    @pytest.fixture
    def store_file(self) -> "StoreFileFixture":
        """Fixture to run prepare and return the result.

        Example usage:

            def test_smoke(store_file: "StoreFileFixture", api):
                store_file(WandbStoragePolicy(api=api), entry_local_path=example_file)
                api.upload_file_retry.assert_called_once()
        """
        return TestStoreFile._store_file

    @pytest.fixture
    def api(self):
        """Fixture to give a mock `internal_api.Api` object, with properly-functioning upload methods."""
        upload_file_retry = Mock()
        upload_multipart_file_chunk_retry = Mock()
        complete_multipart_upload_artifact = Mock()

        return Mock(
            upload_file_retry=upload_file_retry,
            upload_multipart_file_chunk_retry=upload_multipart_file_chunk_retry,
            complete_multipart_upload_artifact=complete_multipart_upload_artifact,
        )

    def test_smoke(self, store_file: "StoreFileFixture", api, example_file: Path):
        store_file(WandbStoragePolicy(api=api), entry_local_path=example_file)
        api.upload_file_retry.assert_called_once()

    def test_uploads_to_prepared_url(
        self, store_file: "StoreFileFixture", api, example_file: Path
    ):
        preparer = mock_preparer(
            prepare=lambda spec: singleton_queue(
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
        assert api.upload_file_retry.call_args[0][0] == "https://wandb-test/dst"

    def test_passes_prepared_headers_to_upload(
        self, store_file: "StoreFileFixture", api, example_file: Path
    ):
        preparer = mock_preparer(
            prepare=lambda spec: singleton_queue(
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
        assert api.upload_file_retry.call_args[1]["extra_headers"] == {
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
            prepare=lambda spec: singleton_queue(
                dummy_response_prepare(spec)._replace(upload_url=upload_url)
            )
        )
        policy = WandbStoragePolicy(api=api)

        deduped = store_file(policy, entry_local_path=example_file, preparer=preparer)
        assert deduped == expect_deduped

        if expect_upload:
            api.upload_file_retry.assert_called_once()
        else:
            api.upload_file_retry.assert_not_called()

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
            api.upload_file_retry.assert_called_once()
        else:
            api.upload_file_retry.assert_not_called()

    @pytest.mark.parametrize("err", [None, Exception("some error")])
    def test_caches_result_on_success(
        self,
        store_file: "StoreFileFixture",
        api,
        example_file: Path,
        artifact_file_cache: ArtifactFileCache,
        err: Optional[Exception],
    ):
        size = example_file.stat().st_size

        api.upload_file_retry = Mock(side_effect=err)
        policy = WandbStoragePolicy(api=api, cache=artifact_file_cache)

        assert not is_cache_hit(artifact_file_cache, "my-digest", size)

        store = functools.partial(store_file, policy, entry_local_path=example_file)

        if err is None:
            store()
            assert is_cache_hit(artifact_file_cache, "my-digest", size)
        else:
            with pytest.raises(Exception, match=err.args[0]):
                store()
            assert not is_cache_hit(artifact_file_cache, "my-digest", size)

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
            prepare=lambda spec: singleton_queue(
                dummy_response_prepare(spec)._replace(
                    upload_url=upload_url, multipart_upload_urls=multipart_upload_urls
                )
            )
        )
        policy = WandbStoragePolicy(api=api)
        # Mock minimum size for multipart so that we can test multipart
        with mock.patch(
            "wandb.sdk.artifacts.storage_policies._multipart.MIN_MULTI_UPLOAD_SIZE",
            example_file.stat().st_size,
        ):
            deduped = self._store_file(
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


@pytest.mark.parametrize("invalid_type", ["job", "wandb-history", "wandb-foo"])
def test_invalid_artifact_type(invalid_type):
    with pytest.raises(ValueError, match="reserved for internal use"):
        Artifact("foo", type=invalid_type)


@given(
    invalid_name=(
        text(  # Too many characters
            alphabet={*ascii_letters, *digits, "_", "-", " "},
            min_size=NAME_MAXLEN + 1,
        )
        | from_regex(  # Contains invalid characters
            r"(\w|\d|\s)*(/)(\w|\d|\s)*",
            fullmatch=True,
        )
    )
)
def test_invalid_artifact_name(invalid_name):
    """Prevent users from instantiating an artifact with an invalid name."""
    with pytest.raises(ValueError):
        _ = Artifact(invalid_name, type="any")


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
        path=path,
        digest="NWQ0MTQwMmFiYzRiMmE3NmI5NzE5ZDkxMTAxN2M1OTI=",
        local_path=path,
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


def test_download_with_pathlib_root(monkeypatch):
    artifact = Artifact("test-artifact", "test-type")
    artifact._state = ArtifactState.COMMITTED
    monkeypatch.setattr(artifact, "_download", lambda *args, **kwargs: "")
    monkeypatch.setattr(artifact, "_download_using_core", lambda *args, **kwargs: "")
    custom_path = Path("some/relative/path")
    artifact.download(custom_path)
    assert len(artifact._download_roots) == 1
    root = list(artifact._download_roots)[0]
    path_parts = custom_path.parts
    assert Path(root).parts[-len(path_parts) :] == path_parts


def test_artifact_multipart_download_threshold():
    mb = 1024 * 1024
    assert should_multipart_download(100 * mb) is False
    assert should_multipart_download(100 * mb, override=True) is True
    assert should_multipart_download(100 * mb, override=False) is False

    assert should_multipart_download(2080 * mb) is True
    assert should_multipart_download(2080 * mb, override=True) is True
    assert should_multipart_download(2080 * mb, override=False) is False

    assert should_multipart_download(5070 * mb) is True
    assert should_multipart_download(5070 * mb, override=True) is True
    assert should_multipart_download(5070 * mb, override=False) is False


def test_artifact_multipart_download_network_error():
    # Disable retries and backoff to avoid timeout in test
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    opener = mock.mock_open()
    url_provider = SharedUrlProvider(
        initial_url="https://invalid.com",
        fetch_fn=lambda: "https://invalid.com",
    )
    with pytest.raises(requests.exceptions.ConnectionError):
        with ThreadPoolExecutor(max_workers=2) as executor:
            multipart_download(
                executor,
                session,
                4 * 1024 * 1024 * 1024,
                opener,
                url_provider,
            )
    opener.return_value.seek.assert_not_called()


@responses.activate()
def test_artifact_multipart_download_disk_error():
    resp = responses.get(
        "http://s3.com/file",
        body=b"test",
        status=200,
    )

    opener = mock.mock_open()
    opener.return_value.write.side_effect = OSError("I/O operation on closed file")
    url_provider = SharedUrlProvider(
        initial_url="https://s3.com/file",
        fetch_fn=lambda: "https://s3.com/file",
    )
    with pytest.raises(OSError):
        with ThreadPoolExecutor(max_workers=2) as executor:
            multipart_download(
                executor,
                requests.Session(),
                500 * 1024 * 1024,  # 500MB should have 5 parts
                opener,
                url_provider,
            )
    # After first get call has errors, remaining get calls should return without making the call.
    # It can be 5 depending on underlying environment, e.g. it fails on windows from time to time.
    assert resp.call_count <= 5


class TestSharedUrlProvider:
    def test_get_url_returns_initial_url(self):
        fetch_fn = Mock(return_value="https://example.com/refreshed")
        provider = SharedUrlProvider(
            initial_url="https://example.com/initial",
            fetch_fn=fetch_fn,
        )

        url = provider.get_url()

        assert url == "https://example.com/initial"
        fetch_fn.assert_not_called()

    def test_get_url_caches_until_invalidated(self):
        fetch_fn = Mock(return_value="https://example.com/refreshed")
        provider = SharedUrlProvider(
            initial_url="https://example.com/initial",
            fetch_fn=fetch_fn,
        )

        url1 = provider.get_url()
        url2 = provider.get_url()

        assert url1 == url2 == "https://example.com/initial"
        fetch_fn.assert_not_called()

    def test_invalidate_forces_refresh(self):
        fetch_fn = Mock(return_value="https://example.com/url1")

        provider = SharedUrlProvider(
            initial_url="https://example.com/initial",
            fetch_fn=fetch_fn,
        )

        url1 = provider.get_url()
        assert url1 == "https://example.com/initial"
        assert fetch_fn.call_count == 0

        provider.invalidate()
        url2 = provider.get_url()

        assert url2 == "https://example.com/url1"
        assert fetch_fn.call_count == 1


@responses.activate()
def test_artifact_multipart_download_retries():
    rsp1 = responses.get(
        "https://s3.com/file/t1",
        body=b"should be some 403 related error message",
        status=403,
    )
    rsp2 = responses.get(
        "https://s3.com/file/t2",
        body=b"test",
        status=200,
    )

    fetch_fn = Mock(return_value="https://s3.com/file/t2")
    url_provider = SharedUrlProvider(
        initial_url="https://s3.com/file/t1",
        fetch_fn=fetch_fn,
    )

    opener = mock.mock_open()

    with ThreadPoolExecutor(max_workers=2) as executor:
        multipart_download(
            executor,
            requests.Session(),
            100,
            opener,
            url_provider,
            part_size=100,
        )

    assert fetch_fn.call_count == 1  # fetched new url once
    assert rsp1.call_count == 1
    assert rsp2.call_count == 1


@responses.activate()
def test_artifact_multipart_download_max_retries_exceeded():
    resp = responses.get(
        "https://s3.com/file",
        body=b"test",
        status=403,
    )

    url_provider = SharedUrlProvider(
        initial_url="https://s3.com/file",
        fetch_fn=lambda: "https://s3.com/file",
    )

    opener = mock.mock_open()

    with pytest.raises(requests.HTTPError):
        with ThreadPoolExecutor(max_workers=2) as executor:
            multipart_download(
                executor,
                requests.Session(),
                100,
                opener,
                url_provider,
                part_size=100,
            )

    assert resp.call_count == 4  # 1 initial + 3 retries
