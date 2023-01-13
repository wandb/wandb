from typing import Callable
from unittest.mock import Mock

import pytest
from wandb.sdk.internal import file_pusher, file_stream, internal_api
from wandb.sdk.internal.artifacts import ArtifactSaver


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
        type="my-type",
        name="my-name",
        client_id="my-client-id",
        sequence_client_id="my-sequence-client-id",
    )

    api.commit_artifact.assert_called_once()


class SomeCustomError(Exception):
    pass


@pytest.mark.timeout(1)
@pytest.mark.parametrize(
    "make_api",
    [
        lambda: make_api(
            use_artifact=Mock(side_effect=SomeCustomError("use_artifact failed"))
        ),
        lambda: make_api(
            create_artifact=Mock(side_effect=SomeCustomError("create_artifact failed"))
        ),
        lambda: make_api(
            create_artifact_manifest=Mock(
                side_effect=SomeCustomError("create_artifact_manifest failed")
            )
        ),
        lambda: make_api(
            upload_file_retry=Mock(
                side_effect=SomeCustomError("upload_file_retry failed")
            )
        ),
        lambda: make_api(
            commit_artifact=Mock(side_effect=SomeCustomError("commit_artifact failed"))
        ),
    ],
)
def test_reraises_err(make_api: Callable[[], internal_api.Api]):
    api = make_api()
    stream = Mock(spec=file_stream.FileStreamApi)
    pusher = file_pusher.FilePusher(api=api, file_stream=stream)

    saver = ArtifactSaver(
        api=api,
        digest="abcd",
        manifest_json=make_manifest_json(),
        file_pusher=pusher,
    )

    with pytest.raises(SomeCustomError):
        saver.save(
            type="my-type",
            name="my-name",
            client_id="my-client-id",
            sequence_client_id="my-sequence-client-id",
            use_after_commit=True,
        )
