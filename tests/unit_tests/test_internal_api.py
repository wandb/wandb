import base64
import hashlib
import os
from pathlib import Path
from unittest.mock import Mock, call

from typing import Any, Callable, Mapping, Optional, Tuple, Type, Union

import pytest
import requests
import responses
import httpx
import respx
from wandb.apis import internal
from wandb.errors import CommError
from wandb.sdk.lib import retry


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

        @pytest.mark.parametrize(
            "error",
            [
                httpx.TimeoutException("my-err"),
                httpx.NetworkError("my-err"),
                httpx.ProxyError("my-err"),
            ],
        )
        def test_returns_transient_error_on_network_errors(
            self,
            mock_httpx: respx.MockRouter,
            some_file: Path,
            error: Exception,
        ):
            mock_httpx.put("http://example.com/upload-dst").mock(side_effect=error)
            with pytest.raises(retry.TransientError):
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

            # TODO(spencerpearson): why did I need to change this?
            assert progress_callback.call_args_list == [
                call(len(file_contents), len(file_contents)),
                call(0, len(file_contents)),
            ]

        @pytest.mark.parametrize(
            "file_size,n_expected_reads",
            [
                # Does it look like these n_expected_reads values are all too big by 1?
                # That's because the Progress doesn't stop iterating until it reads 0 bytes;
                # so there's an extra 0-byte read at the end.
                (0, 1),
                (1, 2),
                # TODO(spencerpearson): we really shouldn't rely on this hidden constant;
                # but the chunk size _is_ out of our control. A conundrum.
                (httpx._content.AsyncIteratorByteStream.CHUNK_SIZE // 2, 2),
                (httpx._content.AsyncIteratorByteStream.CHUNK_SIZE, 2),
                (int(httpx._content.AsyncIteratorByteStream.CHUNK_SIZE * 1.5), 3),
                (int(httpx._content.AsyncIteratorByteStream.CHUNK_SIZE * 2.5), 4),
            ],
        )
        def test_handles_multiple_calls(
            self,
            mock_httpx: respx.MockRouter,
            some_file: Path,
            file_size: int,
            n_expected_reads: int,
        ):
            some_file.write_text(file_size * "x")

            mock_httpx.put("http://example.com/upload-dst").respond(200)

            progress_callback = Mock()
            internal.InternalApi().upload_file(
                "http://example.com/upload-dst",
                some_file.open("rb"),
                callback=progress_callback,
            )

            assert (
                progress_callback.call_count == n_expected_reads
            ), progress_callback.call_args_list

            calls = [c[0] for c in progress_callback.call_args_list]
            for (_, prev_tot), (cur_new, cur_tot) in zip(calls, calls[1:]):
                assert cur_tot == prev_tot + cur_new, calls

            assert calls[-1][1] == file_size

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
