import functools
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from unittest.mock import Mock

import pytest
from wandb.filesync.step_prepare import ResponsePrepare, StepPrepare
from wandb.sdk.wandb_artifacts import (
    ArtifactManifestEntry,
    ArtifactsCache,
    WandbStoragePolicy,
)

if TYPE_CHECKING:
    from wandb.sdk.internal.internal_api import CreateArtifactFileSpecInput


@pytest.fixture
def artifacts_cache(tmp_path: Path) -> ArtifactsCache:
    return ArtifactsCache(tmp_path / "artifacts-cache")


def some_file(tmp_path: Path) -> Path:
    f = tmp_path / "some-file"
    f.write_text("some-content")
    return f


def is_cache_hit(cache: ArtifactsCache, digest: str, size: int) -> bool:
    _, hit, _ = cache.check_md5_obj_path(digest, size)
    return hit


def mock_prepare(
    spec: "CreateArtifactFileSpecInput",
) -> ResponsePrepare:
    name = spec["name"]
    return ResponsePrepare(
        upload_url=f"http://wandb-test/upload-url-{name}",
        upload_headers=["x-my-header-key:my-header-val"],
        birth_artifact_id=f"artifact-id-{name}",
    )


def store_file(
    policy: WandbStoragePolicy,
    artifact_id: str = "my-artifact-id",
    artifact_manifest_id: str = "my-artifact-manifest-id",
    entry_path: str = "my-path",
    entry_digest: str = "my-digest",
    entry_local_path: Optional[Path] = None,
    preparer: Optional[StepPrepare] = None,
) -> bool:
    return policy.store_file(
        artifact_id=artifact_id,
        artifact_manifest_id=artifact_manifest_id,
        entry=ArtifactManifestEntry(
            path=entry_path,
            digest=entry_digest,
            local_path=str(entry_local_path) if entry_local_path else None,
            size=entry_local_path.stat().st_size if entry_local_path else None,
        ),
        preparer=preparer if preparer else Mock(prepare=Mock(wraps=mock_prepare)),
    )


class TestStoreFile:
    def test_smoke(self, tmp_path: Path):
        api = Mock()
        store_file(WandbStoragePolicy(api=api), entry_local_path=some_file(tmp_path))
        api.upload_file_retry.assert_called_once()

    def test_uploads_to_prepared_url(self, tmp_path: Path):
        api = Mock()
        preparer = Mock(
            prepare=lambda spec: mock_prepare(spec)._replace(
                upload_url="https://wandb-test/dst"
            )
        )
        store_file(
            WandbStoragePolicy(api=api),
            entry_local_path=some_file(tmp_path),
            preparer=preparer,
        )
        assert api.upload_file_retry.call_args[0][0] == "https://wandb-test/dst"

    def test_passes_prepared_headers_to_upload(self, tmp_path: Path):
        api = Mock()
        preparer = Mock(
            prepare=lambda spec: mock_prepare(spec)._replace(
                upload_headers=["x-my-header:my-header-val"]
            )
        )
        store_file(
            WandbStoragePolicy(api=api),
            entry_local_path=some_file(tmp_path),
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
        tmp_path: Path,
        upload_url: Optional[str],
        expect_upload: bool,
        expect_deduped: bool,
    ):
        api = Mock()
        preparer = Mock(
            prepare=lambda spec: mock_prepare(spec)._replace(upload_url=upload_url)
        )
        policy = WandbStoragePolicy(api=api)

        deduped = store_file(
            policy, entry_local_path=some_file(tmp_path), preparer=preparer
        )
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
        tmp_path: Path,
        has_local_path: bool,
        expect_upload: bool,
    ):
        api = Mock()
        policy = WandbStoragePolicy(api=api)

        deduped = store_file(
            policy,
            entry_local_path=some_file(tmp_path) if has_local_path else None,
        )
        assert not deduped

        if expect_upload:
            api.upload_file_retry.assert_called_once()
        else:
            api.upload_file_retry.assert_not_called()

    @pytest.mark.parametrize(
        "err",
        [
            None,
            Exception("some error"),
        ],
    )
    def test_caches_result_on_success(
        self,
        tmp_path: Path,
        artifacts_cache: ArtifactsCache,
        err: Optional[Exception],
    ):
        f = some_file(tmp_path)

        api = Mock(upload_file_retry=Mock(side_effect=err))
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
