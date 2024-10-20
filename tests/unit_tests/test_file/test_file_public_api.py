from unittest import mock

from wandb.apis.public.files import File


def test_path_uri_s3_url():
    attrs = {
        "directUrl": "https://my-bucket.s3.us-west-2.amazonaws.com/wandb-artifacts/my-artifact.txt"
    }
    file = File(mock.MagicMock(), attrs)

    assert file.path_uri == "s3://my-bucket/wandb-artifacts/my-artifact.txt"


def test_path_uri_non_s3_url():
    attrs = {
        "directUrl": "https://storage.googleapis.com/wandb-artifacts/my-artifact.txt"
    }
    file = File(mock.MagicMock(), attrs)

    with mock.patch("wandb.termwarn") as mock_termwarn:
        assert file.path_uri == ""
        mock_termwarn.assert_called_once_with(
            "path_uri is only available for files stored in S3"
        )


def test_path_uri_invalid_url():
    attrs = {"directUrl": "not-a-valid-url"}
    file = File(mock.MagicMock(), attrs)

    with mock.patch("wandb.termwarn") as mock_termwarn:
        assert file.path_uri == ""
        mock_termwarn.assert_called_once_with(
            "path_uri is only available for files stored in S3"
        )


def test_path_uri_empty_url():
    attrs = {"directUrl": ""}
    file = File(mock.MagicMock(), attrs)

    with mock.patch("wandb.termwarn") as mock_termwarn:
        assert file.path_uri == ""
        mock_termwarn.assert_called_once_with(
            "path_uri is only available for files stored in S3"
        )


def test_path_uri_missing_direct_url():
    attrs = {}
    file = File(mock.MagicMock(), attrs)

    with mock.patch("wandb.termwarn") as mock_termwarn:
        assert file.path_uri == ""
        mock_termwarn.assert_called_once_with("Unable to find direct_url of file")
