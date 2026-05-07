from unittest import mock

import wandb
from pytest import fixture
from wandb.apis.public.files import File, Files


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


def test_files_convert_objects_skips_invalid_edges(mock_client, mocker):
    run = mocker.MagicMock(project="project", entity="entity", id="run")
    files = Files(mock_client, run)
    files.last_response = {
        "project": {
            "run": {
                "files": {
                    "edges": [
                        None,
                        {"node": None},
                        {"node": {"id": "file-id", "name": "metrics.json"}},
                    ]
                }
            }
        }
    }

    objects = files.convert_objects()

    assert len(objects) == 1
    assert isinstance(objects[0], File)
    assert objects[0].name == "metrics.json"


def test_files_cursor_skips_invalid_edges(mock_client, mocker):
    run = mocker.MagicMock(project="project", entity="entity", id="run")
    files = Files(mock_client, run)
    files.last_response = {
        "project": {
            "run": {
                "files": {
                    "edges": [
                        None,
                        {"node": {"id": "file-id"}},
                        {"cursor": "next-cursor", "node": {"id": "file-id-2"}},
                    ]
                }
            }
        }
    }

    assert files.cursor == "next-cursor"
