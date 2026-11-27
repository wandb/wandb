import numpy as np
import pytest
import wandb
from wandb.proto import wandb_internal_pb2 as pb


@pytest.mark.parametrize("status_code", [429, 500])
def test_retries_retryable_codes(status_code, wandb_backend_spy):
    wandb_backend_spy.stub_filestream(
        "transient error",
        status=status_code,
        n_times=2,  # Should keep retrying until success.
    )

    with wandb.init(
        settings=wandb.Settings(_file_stream_retry_wait_min_seconds=1)
    ) as run:
        run.log({"acc": 1})

    with wandb_backend_spy.freeze() as snapshot:
        assert snapshot.history(run_id=run.id)[0]["acc"] == 1


def test_ignores_malformed_response(wandb_backend_spy):
    wandb_backend_spy.stub_filestream(
        "malformed response",
        status=200,
    )

    with wandb.init() as run:
        run.log({"acc": 1})

    with wandb_backend_spy.freeze() as snapshot:
        assert snapshot.history(run_id=run.id)[0]["acc"] == 1


# The retry behavior is different in the legacy service.


@pytest.mark.parametrize(
    "status_code",
    [400, 401, 403, 404, 409, 410],
)
def test_fails_on_non_retryable_codes(status_code, wandb_backend_spy):
    wandb_backend_spy.stub_filestream(
        "non-retryable error",
        status=status_code,
        n_times=1,  # The first error should cause a failure.
    )

    with wandb.init() as run:
        run.log({"acc": 1})

    # No history should be uploaded.
    with wandb_backend_spy.freeze() as snapshot:
        assert len(snapshot.history(run_id=run.id)) == 0


def test_file_stream_forward_slashes(wandb_backend_spy):
    """
    Tests that the uploaded files have forward slashes.
    As expected by the backend API.
    """
    image = wandb.Image(np.ones((2, 2, 3)))
    with wandb.init() as run:
        run.log({"image": image})

    with wandb_backend_spy.freeze() as snapshot:
        for file in snapshot.uploaded_files(run_id=run.id):
            assert "\\" not in file


def test_gzip_requests_are_processed(user, wandb_backend_spy):
    api = wandb.Api(api_key=user)
    if not api._service_api.feature_enabled(pb.ServerFeature.FILESTREAM_GZIP):
        pytest.skip("Server does not support gzip-compressed filestream requests")

    with wandb.init(
        settings=wandb.Settings(x_file_stream_no_gzip=False),
    ) as run:
        run.log({"acc": 1})

    with wandb_backend_spy.freeze() as snapshot:
        encodings = snapshot.file_stream_content_encodings(run_id=run.id)
        assert encodings
        assert set(encodings) == {"gzip"}
        assert snapshot.history(run_id=run.id)[0]["acc"] == 1
