from unittest import mock

import wandb
from pytest import fixture
from wandb.apis.public.files import File
from wandb.proto import wandb_api_pb2 as apb


@fixture
def mock_client(mocker) -> mock.MagicMock:
    return mocker.MagicMock()


@fixture
def termwarn_spy(mocker) -> mock.MagicMock:
    return mocker.spy(wandb, "termwarn")


def test_path_uri_s3_url(mock_client, termwarn_spy):
    attrs = {
        "directUrl": "https://my-bucket.s3.us-west-2.amazonaws.com/wandb-artifacts/my-artifact.txt"
    }
    file = File(mock_client, attrs)

    assert file.path_uri == "s3://my-bucket/wandb-artifacts/my-artifact.txt"
    termwarn_spy.assert_not_called()


def test_path_uri_s3_url_no_datacenter(mock_client, termwarn_spy):
    attrs = {
        "directUrl": "https://my-bucket.s3.amazonaws.com/wandb-artifacts/my-artifact.txt"
    }
    file = File(mock_client, attrs)

    assert file.path_uri == "s3://my-bucket/wandb-artifacts/my-artifact.txt"
    termwarn_spy.assert_not_called()


def test_path_uri_non_s3_url(mock_client, termwarn_spy):
    attrs = {
        "directUrl": "https://storage.googleapis.com/wandb-artifacts/my-artifact.txt"
    }
    file = File(mock_client, attrs)

    assert file.path_uri == ""
    termwarn_spy.assert_called_once_with(
        "path_uri is only available for files stored in S3"
    )


def test_path_uri_invalid_url(mock_client, termwarn_spy):
    attrs = {"directUrl": "not-a-valid-url"}
    file = File(mock_client, attrs)

    assert file.path_uri == ""
    termwarn_spy.assert_called_once_with(
        "path_uri is only available for files stored in S3"
    )


def test_path_uri_empty_url(mock_client, termwarn_spy):
    attrs = {"directUrl": ""}
    file = File(mock_client, attrs)

    assert file.path_uri == ""
    termwarn_spy.assert_called_once_with("Unable to find direct_url of file")


def test_path_uri_missing_direct_url(mock_client, termwarn_spy):
    attrs = {}
    file = File(mock_client, attrs)

    assert file.path_uri == ""
    termwarn_spy.assert_called_once_with("Unable to find direct_url of file")


def test_path_uri_with_reference_file(mock_client, termwarn_spy):
    attrs = {
        "directUrl": "s3://my-bucket/wandb-artifacts/my-artifact.txt",
        "url": "s3://my-bucket/wandb-artifacts/my-artifact.txt",
    }
    file = File(mock_client, attrs)

    assert file.path_uri == "s3://my-bucket/wandb-artifacts/my-artifact.txt"
    termwarn_spy.assert_not_called()


def test_download_uses_file_service_api(mock_client, tmp_path):
    attrs = {
        "name": "model.bin",
        "url": "https://files.example/model.bin",
        "sizeBytes": 42,
    }
    file = File(mock_client, attrs)
    path = tmp_path / "model.bin"

    def send_api_request(request: apb.ApiRequest) -> apb.ApiResponse:
        with open(request.download_file_request.path, "w") as f:
            f.write("downloaded")
        return apb.ApiResponse(download_file_response=apb.DownloadFileResponse())

    mock_client.send_api_request.side_effect = send_api_request

    with file.download(root=str(tmp_path)) as f:
        assert f.read() == "downloaded"

    request = mock_client.send_api_request.call_args.args[0].download_file_request
    assert request.path == str(path)
    assert request.url == "https://files.example/model.bin"
    assert request.size == 42


def test_download_uses_explicit_api_service_api(mock_client, tmp_path):
    attrs = {
        "name": "model.bin",
        "url": "https://files.example/model.bin",
        "sizeBytes": 42,
    }
    file = File(mock_client, attrs)
    api = mock.MagicMock()
    path = tmp_path / "model.bin"

    def send_api_request(request: apb.ApiRequest) -> apb.ApiResponse:
        with open(request.download_file_request.path, "w") as f:
            f.write("downloaded")
        return apb.ApiResponse(download_file_response=apb.DownloadFileResponse())

    api._service_api.send_api_request.side_effect = send_api_request

    with file.download(root=str(tmp_path), api=api) as f:
        assert f.read() == "downloaded"

    mock_client.send_api_request.assert_not_called()
    request = api._service_api.send_api_request.call_args.args[0].download_file_request
    assert request.path == str(path)
    assert request.url == "https://files.example/model.bin"
    assert request.size == 42
