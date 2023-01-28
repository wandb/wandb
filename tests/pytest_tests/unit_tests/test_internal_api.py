import asyncio
import base64
import concurrent.futures
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


@pytest.fixture
def mock_responses():
    with responses.RequestsMock() as rsps:
        yield rsps


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


MockResponseOrException = Union[Exception, Tuple[int, Mapping[int, int], str]]


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
            "response,expected_errtype",
            [
                ((400, {}, ""), requests.exceptions.HTTPError),
                ((500, {}, ""), retry.TransientError),
                ((502, {}, ""), retry.TransientError),
                (requests.exceptions.ConnectionError(), retry.TransientError),
                (requests.exceptions.Timeout(), retry.TransientError),
                (RuntimeError("oh no"), RuntimeError),
            ],
        )
        def test_returns_transienterror_on_transient_issues(
            self,
            mock_responses: responses.RequestsMock,
            some_file: Path,
            response: MockResponseOrException,
            expected_errtype: Type[Exception],
        ):
            mock_responses.add_callback(
                "PUT",
                "http://example.com/upload-dst",
                Mock(return_value=response),
            )
            with pytest.raises(expected_errtype):
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
                (400, {}, ""),
                (500, {}, ""),
            ],
        )
        def test_rewinds_on_failure(
            self,
            mock_responses: responses.RequestsMock,
            some_file: Path,
            failure: MockResponseOrException,
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
            with pytest.raises((retry.TransientError, requests.RequestException)):
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
        "request_headers,response,expected_errtype",
        [
            (
                {"x-amz-meta-md5": "1234"},
                (400, {}, "blah blah RequestTimeout blah blah"),
                retry.TransientError,
            ),
            (
                {"x-amz-meta-md5": "1234"},
                (400, {}, "non-timeout-related error message"),
                requests.RequestException,
            ),
            (
                {"x-amz-meta-md5": "1234"},
                requests.exceptions.ConnectionError(),
                retry.TransientError,
            ),
            (
                {},
                (400, {}, "blah blah RequestTimeout blah blah"),
                requests.RequestException,
            ),
        ],
    )
    def test_transient_failure_on_special_aws_request_timeout(
        self,
        mock_responses: responses.RequestsMock,
        some_file: Path,
        request_headers: Mapping[str, str],
        response,
        expected_errtype: Type[Exception],
    ):
        mock_responses.add_callback(
            "PUT", "http://example.com/upload-dst", Mock(return_value=response)
        )
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
            "response,expected_errtype,check_err",
            [
                (
                    (400, {}, "my-reason"),
                    requests.RequestException,
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
            response: MockResponseOrException,
            expected_errtype: Type[Exception],
            check_err: Callable[[Exception], bool],
        ):
            mock_responses.add_callback(
                "PUT", "https://example.com/foo/bar/baz", Mock(return_value=response)
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
        mock_responses: responses.RequestsMock,
        schedule: Sequence[int],
        num_requests: int,
    ):
        handler = Mock(side_effect=[(status, {}, "") for status in schedule])
        mock_responses.add_callback("PUT", "http://example.com/upload-dst", handler)

        internal.InternalApi().upload_file_retry(
            "http://example.com/upload-dst",
            some_file.open("rb"),
        )

        assert handler.call_count == num_requests

    def test_stops_after_bad_status(
        self,
        some_file: Path,
        mock_responses: responses.RequestsMock,
    ):
        handler = Mock(side_effect=[(400, {}, "")])
        mock_responses.add_callback("PUT", "http://example.com/upload-dst", handler)

        with pytest.raises(wandb.errors.CommError):
            internal.InternalApi().upload_file_retry(
                "http://example.com/upload-dst",
                some_file.open("rb"),
            )
        assert handler.call_count == 1

    def test_stops_after_retry_limit_exceeded(
        self,
        some_file: Path,
        mock_responses: responses.RequestsMock,
    ):
        num_retries = 8
        handler = Mock(return_value=(500, {}, ""))
        mock_responses.add_callback("PUT", "http://example.com/upload-dst", handler)

        with pytest.raises(wandb.errors.CommError):
            internal.InternalApi().upload_file_retry(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                num_retries=num_retries,
            )

        assert handler.call_count == num_retries + 1


class TestUploadFileRetryAsync:
    @pytest.fixture(autouse=True)
    def mock_sleep(self, monkeypatch: pytest.MonkeyPatch):
        async def _sleep(dur):
            pass

        monkeypatch.setattr(asyncio, "sleep", _sleep)

    @pytest.mark.parametrize(
        ["schedule", "num_requests"],
        [
            ([200], 1),
            ([500, 500, 200], 3),
        ],
    )
    def test_stops_after_success(
        self,
        some_file: Path,
        mock_respx: "respx.MockRouter",
        schedule: Sequence[int],
        num_requests: int,
    ):
        route = mock_respx.put("http://example.com/upload-dst")
        route.side_effect = [httpx.Response(status) for status in schedule]

        asyncio.run(
            internal.InternalApi().upload_file_retry_async(
                "http://example.com/upload-dst",
                some_file.open("rb"),
            )
        )

        assert route.call_count == num_requests

    def test_stops_after_bad_status(
        self,
        some_file: Path,
        mock_respx: "respx.MockRouter",
    ):
        route = mock_respx.put("http://example.com/upload-dst")
        route.side_effect = [httpx.Response(400)]

        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(
                internal.InternalApi().upload_file_retry_async(
                    "http://example.com/upload-dst",
                    some_file.open("rb"),
                )
            )
        assert route.call_count == 1

    def test_stops_after_retry_limit_exceeded(
        self,
        some_file: Path,
        mock_respx: "respx.MockRouter",
    ):
        num_retries = 8
        route = mock_respx.put("http://example.com/upload-dst")
        route.side_effect = httpx.Response(500)

        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(
                internal.InternalApi().upload_file_retry_async(
                    "http://example.com/upload-dst",
                    some_file.open("rb"),
                    num_retries=num_retries,
                )
            )

        assert route.call_count == num_retries + 1

    @pytest.mark.parametrize(
        ["headers", "expect_delegate"],
        [
            ({}, False),
            ({"x-ms-blob-type": "BlockBlob"}, True),
        ],
    )
    def test_delegates_to_sync_upload_if_azure(
        self,
        some_file: Path,
        mock_respx: "respx.MockRouter",
        headers: Mapping[str, str],
        expect_delegate: bool,
    ):
        if not expect_delegate:
            mock_respx.put("http://example.com/upload-dst").mock(
                return_value=httpx.Response(200)
            )

        executor = concurrent.futures.ThreadPoolExecutor()
        executor.submit = Mock(wraps=executor.submit)

        api = internal.InternalApi()
        api.upload_file_retry = Mock()

        loop = asyncio.new_event_loop()
        loop.set_default_executor(executor)
        loop.run_until_complete(
            api.upload_file_retry_async(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                extra_headers=headers,
            )
        )

        if expect_delegate:
            api.upload_file_retry.assert_called_once()
            executor.submit.assert_called_once()
        else:
            api.upload_file_retry.assert_not_called()
            executor.submit.assert_not_called()
