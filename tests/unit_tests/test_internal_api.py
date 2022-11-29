import base64
import hashlib
import io
import os
import tempfile
from pathlib import Path
from typing import Callable, Mapping, Optional
from unittest.mock import Mock, call

import azure.core.exceptions
import azure.core.pipeline.transport._requests_basic

# TODO(spencerpearson): DO NOT MERGE
# Does ^this import need to be guarded so that people can
# run the whole test suite without this lib?
import pytest
import requests
import responses
from wandb.apis import internal
from wandb.errors import CommError
from wandb.sdk.lib import retry
from wandb.sdk.internal.internal_api import _guess_response_content


def test_agent_heartbeat_with_no_agent_id_fails():
    a = internal.Api()
    with pytest.raises(ValueError):
        a.agent_heartbeat(None, {}, {})


def test_get_run_state_invalid_kwargs():
    with pytest.raises(CommError) as e:
        _api = internal.Api()

        def _mock_gql(*args, **kwargs):
            return dict()

        _api.api.gql = _mock_gql
        _api.get_run_state("test_entity", None, "test_run")

    assert "Error fetching run state" in str(e.value)


@pytest.mark.parametrize(
    "existing_contents,expect_download",
    [
        (None, True),
        ("outdated contents", True),
        ("current contents", False),
    ],
)
def test_download_write_file_fetches_iff_file_checksum_mismatched(
    existing_contents: Optional[str],
    expect_download: bool,
):
    url = "https://example.com/path/to/file.txt"
    current_contents = "current contents"
    with responses.RequestsMock() as rsps, tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "file.txt")

        if expect_download:
            rsps.add(
                responses.GET,
                url,
                body=current_contents,
            )

        if existing_contents is not None:
            with open(filepath, "w") as f:
                f.write(existing_contents)

        _, response = internal.InternalApi().download_write_file(
            metadata={
                "name": filepath,
                "md5": base64.b64encode(
                    hashlib.md5(current_contents.encode()).digest()
                ).decode(),
                "url": url,
            },
            out_dir=tmpdir,
        )

        if expect_download:
            assert response is not None
        else:
            assert response is None


@pytest.fixture
def some_file(tmp_path: Path):
    p = tmp_path / "some_file.txt"
    p.write_text("some text")
    return p


class TestUploadFile:
    class TestSimple:
        def test_adds_headers_to_request(
            self, mock_responses: responses.RequestsMock, some_file: Path
        ):
            response_callback = Mock(return_value=(200, {}, "success!"))
            mock_responses.add_callback(
                "PUT", "http://example.com/upload-dst", response_callback
            )
            internal.InternalApi().upload_file(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                extra_headers={"X-Test": "test"},
            )
            assert response_callback.call_args[0][0].headers["X-Test"] == "test"

        def test_returns_response_on_success(
            self, mock_responses: responses.RequestsMock, some_file: Path
        ):
            mock_responses.add(
                "PUT", "http://example.com/upload-dst", status=200, body="success!"
            )
            resp = internal.InternalApi().upload_file(
                "http://example.com/upload-dst", some_file.open("rb")
            )
            assert resp.content == b"success!"

        @pytest.mark.parametrize(
            "status,transient", [(400, False), (500, True), (502, True)]
        )
        def test_returns_transient_error_on_transient_statuscodes(
            self,
            mock_responses: responses.RequestsMock,
            some_file: Path,
            status: int,
            transient: bool,
        ):
            mock_responses.add(
                "PUT", "http://example.com/upload-dst", status=status, body="failure!"
            )
            with pytest.raises(
                retry.TransientError if transient else requests.exceptions.HTTPError
            ):
                internal.InternalApi().upload_file(
                    "http://example.com/upload-dst", some_file.open("rb")
                )

        @pytest.mark.parametrize(
            "error",
            [requests.exceptions.ConnectionError(), requests.exceptions.Timeout()],
        )
        def test_returns_transient_error_on_network_errors(
            self,
            mock_responses: responses.RequestsMock,
            some_file: Path,
            error: Exception,
        ):
            mock_responses.add("PUT", "http://example.com/upload-dst", body=error)
            with pytest.raises(retry.TransientError):
                internal.InternalApi().upload_file(
                    "http://example.com/upload-dst", some_file.open("rb")
                )

    class TestProgressCallback:
        def test_smoke(self, mock_responses: responses.RequestsMock, some_file: Path):
            file_contents = "some text"
            some_file.write_text(file_contents)

            def response_callback(request: requests.models.PreparedRequest):
                assert request.body.read() == file_contents.encode()
                return (200, {}, "success!")

            mock_responses.add_callback(
                "PUT", "http://example.com/upload-dst", response_callback
            )

            progress_callback = Mock()
            internal.InternalApi().upload_file(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                callback=progress_callback,
            )

            assert progress_callback.call_args_list == [
                call(len(file_contents), len(file_contents))
            ]

        def test_handles_multiple_calls(
            self, mock_responses: responses.RequestsMock, some_file: Path
        ):
            some_file.write_text("12345")

            def response_callback(request: requests.models.PreparedRequest):
                assert request.body.read(2) == b"12"
                assert request.body.read(2) == b"34"
                assert request.body.read() == b"5"
                assert request.body.read() == b""
                return (200, {}, "success!")

            mock_responses.add_callback(
                "PUT", "http://example.com/upload-dst", response_callback
            )

            progress_callback = Mock()
            internal.InternalApi().upload_file(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                callback=progress_callback,
            )

            assert progress_callback.call_args_list == [
                call(2, 2),
                call(2, 4),
                call(1, 5),
                call(0, 5),
            ]

        @pytest.mark.parametrize(
            "failure",
            [
                requests.exceptions.Timeout(),
                requests.exceptions.ConnectionError(),
                (500, {}, ""),
            ],
        )
        def test_rewinds_on_failure(
            self, mock_responses: responses.RequestsMock, some_file: Path, failure
        ):
            some_file.write_text("1234567")

            def response_callback(request: requests.models.PreparedRequest):
                assert request.body.read(2) == b"12"
                assert request.body.read(2) == b"34"
                return failure

            mock_responses.add_callback(
                "PUT", "http://example.com/upload-dst", response_callback
            )

            progress_callback = Mock()
            with pytest.raises(Exception):
                internal.InternalApi().upload_file(
                    "http://example.com/upload-dst",
                    some_file.open("rb"),
                    callback=progress_callback,
                )

            assert progress_callback.call_args_list == [
                call(2, 2),
                call(2, 4),
                call(-4, 0),
            ]

    @pytest.mark.parametrize(
        "request_headers,response,transient",
        [
            (
                {"x-amz-meta-md5": "1234"},
                (400, {}, "blah blah RequestTimeout blah blah"),
                True,
            ),
            (
                {"x-amz-meta-md5": "1234"},
                (400, {}, "non-timeout-related error message"),
                False,
            ),
            (
                {"x-amz-meta-md5": "1234"},
                (401, {}, "blah blah RequestTimeout blah blah"),
                False,
            ),
            (
                {"x-amz-meta-md5": "1234"},
                requests.exceptions.ConnectionError(),
                True,
            ),
            (
                {},
                (400, {}, "blah blah RequestTimeout blah blah"),
                False,
            ),
        ],
    )
    def test_transient_failure_on_special_aws_request_timeout(
        self,
        mock_responses: responses.RequestsMock,
        some_file: Path,
        request_headers: Mapping[str, str],
        response,
        transient: bool,
    ):
        mock_responses.add_callback(
            "PUT", "http://example.com/upload-dst", lambda _: response
        )
        with pytest.raises(
            retry.TransientError if transient else requests.exceptions.HTTPError
        ):
            internal.InternalApi().upload_file(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                extra_headers=request_headers,
            )

    class TestAzure:
        MAGIC_HEADERS = {"x-ms-blob-type": "SomeBlobType"}

        @pytest.mark.parametrize(
            "request_headers,uses_azure_lib",
            [
                ({}, False),
                (MAGIC_HEADERS, True),
            ],
        )
        def test_uses_azure_lib_if_available(
            self,
            mock_responses: responses.RequestsMock,
            some_file: Path,
            request_headers: Mapping[str, str],
            uses_azure_lib: bool,
        ):
            api = internal.InternalApi()

            if uses_azure_lib:
                api._azure_blob_module = Mock()
            else:
                mock_responses.add("PUT", "http://example.com/upload-dst")

            api.upload_file(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                extra_headers=request_headers,
            )

            if uses_azure_lib:
                api._azure_blob_module.BlobClient.from_blob_url().upload_blob.assert_called_once()
            else:
                assert len(mock_responses.calls) == 1

        @pytest.mark.parametrize(
            "azure_err,check_normal_err",
            [
                (
                    azure.core.exceptions.HttpResponseError(
                        response=Mock(
                            status_code=400,
                            headers={},
                            internal_response=io.BytesIO(b"err details"),
                        )
                    ),
                    lambda errinfo: isinstance(
                        errinfo.value, requests.exceptions.RequestException
                    )
                    and errinfo.value.response.status_code == 400,
                ),
                (
                    azure.core.exceptions.AzureError("something wild"),
                    lambda errinfo: isinstance(errinfo.value, retry.TransientError),
                ),
            ],
        )
        def test_translates_azure_err_to_normal_err(
            self,
            some_file: Path,
            azure_err: azure.core.exceptions.AzureError,
            check_normal_err: Callable[["pytest.ExceptionInfo"], bool],
        ):
            api = internal.InternalApi()
            api._azure_blob_module = Mock()
            api._azure_blob_module.BlobClient.from_blob_url().upload_blob.side_effect = (
                azure_err
            )

            with pytest.raises(
                (requests.exceptions.RequestException, retry.TransientError)
            ) as e:
                api.upload_file(
                    "http://example.com/upload-dst",
                    some_file.open("rb"),
                    extra_headers=self.MAGIC_HEADERS,
                )

            assert check_normal_err(e), e


class TestGuessResponseContent:
    def test_requests(self):
        resp = requests.Response()
        assert _guess_response_content(resp) == b"<None>"

        resp = requests.Response()
        resp.raw = io.BytesIO(b"foo")
        assert _guess_response_content(resp) == b"foo"

        resp = requests.Response()
        resp.raw = object()  # should raise when trying to read
        assert _guess_response_content(resp) == b"<unknown>"

    def test_azure(self):
        resp = azure.core.pipeline.transport.HttpResponse(
            request=Mock(),
            internal_response=io.BytesIO(b"foo"),
        )
        assert _guess_response_content(resp) == b"foo"

        internal_response = requests.Response()
        internal_response.raw = io.BytesIO(b"foo")
        resp = azure.core.exceptions.HttpResponseError(
            response=azure.core.pipeline.transport._requests_basic.HttpResponse(
                request=Mock(),
                internal_response=internal_response,
            )
        )
        assert _guess_response_content(resp) == b"foo"

    def test_misc(self):
        assert _guess_response_content(None) == b"<unknown>"
        assert _guess_response_content(object()) == b"<unknown>"
        assert _guess_response_content(Exception()) == b"<unknown>"
        assert _guess_response_content([]) == b"<unknown>"
        assert _guess_response_content(Mock()) == b"<unknown>"
        assert (
            _guess_response_content(Mock(read=Mock(side_effect=Exception())))
            == b"<unknown>"
        )
