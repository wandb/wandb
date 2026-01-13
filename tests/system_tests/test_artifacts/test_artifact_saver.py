from __future__ import annotations

from unittest.mock import Mock

from pytest import mark, raises
from wandb.sdk.artifacts.artifact_saver import ArtifactSaver
from wandb.sdk.internal import file_pusher, file_stream, internal_api


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
        {file: {"url": f"http://wandb-test/{file}"} for file in files},
    )


def make_api(**kwargs) -> Mock:
    return Mock(
        spec=internal_api.Api,
        **{
            "create_artifact": Mock(
                return_value=(
                    {"id": "my-artifact-id", "state": "PENDING"},
                    None,
                )
            ),
            "create_artifact_manifest": Mock(
                return_value=(
                    "my-artifact-manifest-id",
                    {
                        "uploadUrl": "http://wandb-test/dst",
                        "uploadHeaders": ["x-my-header-key:my-header-val"],
                    },
                )
            ),
            "upload_urls": Mock(wraps=mock_upload_urls),
            "upload_file_retry": Mock(),
            **kwargs,
        },
    )


def make_manifest_json() -> dict:
    return {
        "version": 1,
        "storagePolicy": "wandb-storage-policy-v1",
        "storagePolicyConfig": {"storageLayout": "V2"},
        "contents": {},
    }


def test_calls_commit_on_success():
    api = make_api()
    stream = Mock(spec=file_stream.FileStreamApi)
    pusher = file_pusher.FilePusher(api=api, file_stream=stream)

    saver = ArtifactSaver(
        api=api,
        digest="abcd",
        manifest_json=make_manifest_json(),
        file_pusher=pusher,
    )

    saver.save(
        entity="my-entity",
        project="my-project",
        type="my-type",
        name="my-name",
        client_id="my-client-id",
        sequence_client_id="my-sequence-client-id",
    )

    api.commit_artifact.assert_called_once()


@mark.timeout(1)
class TestReraisesErr:
    def _save_artifact(self, api: Mock):
        stream = Mock(spec=file_stream.FileStreamApi)
        pusher = file_pusher.FilePusher(api=api, file_stream=stream)

        saver = ArtifactSaver(
            api=api,
            digest="abcd",
            manifest_json=make_manifest_json(),
            file_pusher=pusher,
        )

        saver.save(
            entity="my-entity",
            project="my-project",
            type="my-type",
            name="my-name",
            client_id="my-client-id",
            sequence_client_id="my-sequence-client-id",
            use_after_commit=True,
        )

    def test_use_artifact_err_reraised(self):
        exc = Exception("test-exc")
        with raises(Exception, match="test-exc"):
            self._save_artifact(api=make_api(use_artifact=Mock(side_effect=exc)))

    def test_create_artifact_err_reraised(self):
        exc = Exception("test-exc")
        with raises(Exception, match="test-exc"):
            self._save_artifact(api=make_api(create_artifact=Mock(side_effect=exc)))

    def test_create_artifact_manifest_err_reraised(self):
        exc = Exception("test-exc")
        with raises(Exception, match="test-exc"):
            self._save_artifact(
                api=make_api(create_artifact_manifest=Mock(side_effect=exc))
            )

    def test_upload_file_retry_err_reraised(self):
        exc = Exception("test-exc")
        with raises(Exception, match="test-exc"):
            self._save_artifact(api=make_api(upload_file_retry=Mock(side_effect=exc)))

    def test_commit_artifact_err_reraised(self):
        exc = Exception("test-exc")
        with raises(Exception, match="test-exc"):
            self._save_artifact(api=make_api(commit_artifact=Mock(side_effect=exc)))
