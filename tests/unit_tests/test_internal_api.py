import base64
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple, Type, Union
from unittest.mock import Mock, call

import httpx
import pytest
import requests
import responses
import respx
import wandb.errors
from wandb.apis import internal
from wandb.errors import CommError
from wandb.sdk.lib import retry

from .test_retry import MockTime, mock_time  # noqa: F401


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


@pytest.fixture
def mock_httpx():
    with respx.MockRouter() as router:
        yield router


class TestUploadFile:
    class TestSimple:
        def test_adds_headers_to_request(
            self, mock_httpx: respx.MockRouter, some_file: Path
        ):
            response_callback = Mock(return_value=httpx.Response(200))
            mock_httpx.put("http://example.com/upload-dst").mock(
                side_effect=response_callback
            )
            internal.InternalApi().upload_file(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                extra_headers={"X-Test": "test"},
            )
            assert response_callback.call_args[0][0].headers["X-Test"] == "test"

        def test_returns_response_on_success(
            self, mock_httpx: respx.MockRouter, some_file: Path
        ):
            mock_httpx.put("http://example.com/upload-dst").respond(
                200, text="success!"
            )
            resp = internal.InternalApi().upload_file(
                "http://example.com/upload-dst", some_file.open("rb")
            )
            assert resp.content == b"success!"

        @pytest.mark.parametrize(
            "response,expected_errtype",
            [
                (lambda _: httpx.Response(400), httpx.HTTPStatusError),
                (lambda _: httpx.Response(500), retry.TransientError),
                (lambda _: httpx.Response(502), retry.TransientError),
                (httpx.NetworkError("my-err"), retry.TransientError),
                (httpx.TimeoutException("my-err"), retry.TransientError),
                (RuntimeError("oh no"), RuntimeError),
            ],
        )
        def test_returns_transienterror_on_transient_issues(
            self,
            mock_httpx: respx.MockRouter,
            some_file: Path,
            response: Union[Exception, Callable[[httpx.Request], httpx.Response]],
            expected_errtype: Type[Exception],
        ):
            mock_httpx.put("http://example.com/upload-dst").mock(side_effect=response)
            with pytest.raises(expected_errtype):
                internal.InternalApi().upload_file(
                    "http://example.com/upload-dst", some_file.open("rb")
                )

    class TestProgressCallback:
        def test_smoke(self, mock_httpx: respx.MockRouter, some_file: Path):
            file_contents = "some text"
            some_file.write_text(file_contents)

            def response_callback(request: httpx.Request):
                assert request.content == file_contents.encode()
                return httpx.Response(200)

            mock_httpx.put("http://example.com/upload-dst").mock(
                side_effect=response_callback
            )

            progress_callback = Mock()
            internal.InternalApi().upload_file(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                callback=progress_callback,
            )

            assert progress_callback.call_args_list == [
                call(len(file_contents), len(file_contents)),
                call(0, len(file_contents)),
            ]

        def test_handles_multiple_calls(
            self,
            mock_httpx: respx.MockRouter,
            some_file: Path,
        ):
            some_file.write_text("12345")

            mock_httpx.put("http://example.com/upload-dst").respond(200)

            # We can't directly control the chunk size httpx uses for reading our file,
            # so instead, we'll wrap a mock around the file, and replace its read() method
            # to just return 2 bytes at a time. It's officially acceptable for read() to
            # return fewer bytes than requested, without that necessarily meaning EOF.
            # (Well, technically `min(n,2)` bytes at a time, to obey read()'s contract of
            #  (a) not returning more bytes than asked for, and
            #  (b) returning the whole contents on `read()` or `read(-1)`.
            #  See https://docs.python.org/3/library/io.html#io.RawIOBase.read )
            real_file = some_file.open("rb")
            mock_file = Mock(
                wraps=real_file,
                read=lambda n=-1: real_file.read(min(n, 2)),
            )

            progress_callback = Mock()

            internal.InternalApi().upload_file(
                "http://example.com/upload-dst",
                mock_file,
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
                httpx.TimeoutException("my-err"),
                httpx.NetworkError("my-err"),
                httpx.Response(500),
            ],
        )
        def test_rewinds_on_failure(
            self,
            mock_httpx: respx.MockRouter,
            some_file: Path,
            failure: Union[Exception, httpx.Response],
        ):
            some_file.write_text("1234567")

            mock_httpx.put("http://example.com/upload-dst").mock(side_effect=failure)

            progress_callback = Mock()
            with pytest.raises(Exception):
                internal.InternalApi().upload_file(
                    "http://example.com/upload-dst",
                    some_file.open("rb"),
                    callback=progress_callback,
                )

            assert progress_callback.call_args_list == [
                call(7, 7),
                call(0, 7),
                call(-7, 0),
            ]

    @pytest.mark.parametrize(
        "request_headers,response,expected_errtype",
        [
            (
                {"x-amz-meta-md5": "1234"},
                httpx.Response(400, text="blah blah RequestTimeout blah blah"),
                retry.TransientError,
            ),
            (
                {"x-amz-meta-md5": "1234"},
                httpx.Response(400, text="non-timeout-related error message"),
                httpx.HTTPStatusError,
            ),
            (
                {"x-amz-meta-md5": "1234"},
                httpx.NetworkError("my-err"),
                retry.TransientError,
            ),
            (
                {},
                httpx.Response(400, text="blah blah RequestTimeout blah blah"),
                httpx.HTTPStatusError,
            ),
        ],
    )
    def test_transient_failure_on_special_aws_request_timeout(
        self,
        mock_httpx: respx.MockRouter,
        some_file: Path,
        request_headers: Mapping[str, str],
        response: Union[Exception, httpx.Response],
        expected_errtype: Type[Exception],
    ):
        mock_httpx.put("http://example.com/upload-dst").mock(side_effect=response)
        with pytest.raises(expected_errtype):
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
            mock_httpx: respx.MockRouter,
            some_file: Path,
            request_headers: Mapping[str, str],
            uses_azure_lib: bool,
        ):
            api = internal.InternalApi()

            if uses_azure_lib:
                api._azure_blob_module = Mock()
            else:
                mock_httpx.put("http://example.com/upload-dst")

            api.upload_file(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                extra_headers=request_headers,
            )

            if uses_azure_lib:
                api._azure_blob_module.BlobClient.from_blob_url().upload_blob.assert_called_once()
            else:
                assert len(mock_httpx.calls) == 1

        @pytest.mark.parametrize(
            "response,expected_errtype,check_err",
            [
                (
                    (400, {}, "my-reason"),
                    httpx.HTTPStatusError,
                    lambda e: e.response.status_code == 400 and "my-reason" in str(e),
                ),
                (
                    (500, {}, "my-reason"),
                    retry.TransientError,
                    lambda e: (
                        e.exception.response.status_code == 500
                        and "my-reason" in str(e.exception)
                    ),
                ),
                (
                    requests.exceptions.ConnectionError("my-reason"),
                    retry.TransientError,
                    lambda e: "my-reason" in str(e.exception),
                ),
            ],
        )
        def test_translates_azure_err_to_normal_err(
            self,
            mock_responses: responses.RequestsMock,
            some_file: Path,
            response: Union[Exception, Tuple[int, Mapping[str, str], str]],
            expected_errtype: Type[Exception],
            check_err: Callable[[Exception], bool],
        ):
            mock_responses.add_callback(
                "PUT", "https://example.com/foo/bar/baz", lambda _: response
            )
            with pytest.raises(expected_errtype) as e:
                internal.InternalApi().upload_file(
                    "https://example.com/foo/bar/baz",
                    some_file.open("rb"),
                    extra_headers=self.MAGIC_HEADERS,
                )

            assert check_err(e.value), e.value


class TestUploadFileRetry:
    """Tests the retry logic of upload_file_retry.

    Testing the file-upload logic itself is done in TestUploadFile, above;
    this class just tests the retry logic (though it does make a couple
    assumptions about status codes, like "400 isn't retriable, 500 is.")
    """

    @pytest.mark.parametrize(
        ["schedule", "num_requests"],
        [
            ([200, 0], 1),
            ([500, 500, 200, 0], 3),
        ],
    )
    def test_stops_after_success(
        self,
        some_file: Path,
        mock_httpx: respx.MockRouter,
        schedule: Sequence[int],
        num_requests: int,
    ):
        handler = Mock(side_effect=[httpx.Response(status) for status in schedule])
        mock_httpx.put("http://example.com/upload-dst").mock(side_effect=handler)

        internal.InternalApi().upload_file_retry(
            "http://example.com/upload-dst",
            some_file.open("rb"),
        )

        assert handler.call_count == num_requests

    def test_stops_after_bad_status(
        self,
        some_file: Path,
        mock_httpx: respx.MockRouter,
    ):
        handler = Mock(return_value=httpx.Response(400))
        mock_httpx.put("http://example.com/upload-dst").mock(side_effect=handler)

        with pytest.raises(wandb.errors.CommError):
            internal.InternalApi().upload_file_retry(
                "http://example.com/upload-dst",
                some_file.open("rb"),
            )
        assert handler.call_count == 1

    def test_stops_after_retry_limit_exceeded(
        self,
        some_file: Path,
        mock_httpx: respx.MockRouter,
    ):
        num_retries = 8
        handler = Mock(return_value=httpx.Response(500))
        mock_httpx.put("http://example.com/upload-dst").mock(side_effect=handler)

        with pytest.raises(wandb.errors.CommError):
            internal.InternalApi().upload_file_retry(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                num_retries=num_retries,
            )

        assert handler.call_count == num_retries + 1
