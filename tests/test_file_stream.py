"""
file_stream tests.
"""

from __future__ import print_function
from dataclasses import dataclass

import json
import pytest
import os

from wandb.sdk.internal.file_stream import CRDedupeFilePolicy
from wandb.sdk.lib import file_stream_utils
from wandb import util


def generate_history():
    history = []
    history.append(dict(step=0, data=dict(v1=1, v2=2, v3="dog", mystep=1)))
    history.append(dict(step=1, data=dict(v1=3, v2=8, v3="cat", mystep=2)))
    return history


def convert_history(history_data):
    history = []
    for h in history_data:
        step = h["step"]
        data = h["data"]
        data["_step"] = step
        history.append(data)
    return history


def assert_history(publish_util, dropped=None):
    history = generate_history()
    ctx_util = publish_util(history=history)

    converted_history = convert_history(history)
    assert ctx_util.history == converted_history
    if dropped is not None:
        assert ctx_util.dropped_chunks == dropped


def test_fstream_resp_limits_none(publish_util, mock_server, inject_requests):
    resp_normal = json.dumps({"exitcode": None})

    match = inject_requests.Match(path_suffix="/file_stream")
    inject_requests.add(match=match, response=resp_normal)
    assert_history(publish_util)


def test_fstream_resp_limits_valid(publish_util, mock_server, inject_requests):
    dynamic_settings = {"heartbeat_seconds": 10}
    resp_limits = json.dumps({"exitcode": None, "limits": dynamic_settings})

    match = inject_requests.Match(path_suffix="/file_stream")
    inject_requests.add(match=match, response=resp_limits)
    assert_history(publish_util)
    # note: we are not testing that the limits changed, only that they were accepted


def test_fstream_resp_limits_malformed(publish_util, mock_server, inject_requests):
    dynamic_settings = {"heartbeat_seconds": 10}
    resp_limits = json.dumps({"exitcode": None, "limits": "junk"})

    match = inject_requests.Match(path_suffix="/file_stream")
    inject_requests.add(match=match, response=resp_limits)
    assert_history(publish_util)


def test_fstream_resp_malformed(publish_util, mock_server, inject_requests):
    resp_invalid = "invalid json {junk broken]"

    match = inject_requests.Match(path_suffix="/file_stream")
    inject_requests.add(match=match, response=resp_invalid)
    assert_history(publish_util)


def test_fstream_status_500(publish_util, mock_server, inject_requests):

    match = inject_requests.Match(path_suffix="/file_stream", count=2)
    inject_requests.add(match=match, http_status=500)
    assert_history(publish_util)


def test_fstream_status_429(publish_util, mock_server, inject_requests):
    """Rate limiting test."""

    match = inject_requests.Match(path_suffix="/file_stream", count=2)
    inject_requests.add(match=match, http_status=429)
    assert_history(publish_util)


def test_fstream_status_404(publish_util, mock_server, inject_requests, capsys):

    match = inject_requests.Match(path_suffix="/file_stream", count=2)
    inject_requests.add(match=match, http_status=404)
    assert_history(publish_util, dropped=1)
    stdout, stderr = capsys.readouterr()
    assert "Dropped streaming file chunk" in stderr


def test_fstream_status_max_retries(
    publish_util, mock_server, inject_requests, mocker, capsys
):
    # set short max sleep so we can exhaust retries
    mocker.patch("wandb.wandb_sdk.internal.file_stream.MAX_SLEEP_SECONDS", 0.1)

    match = inject_requests.Match(path_suffix="/file_stream")
    inject_requests.add(match=match, http_status=500)
    assert_history(publish_util, dropped=1)
    stdout, stderr = capsys.readouterr()
    assert "Dropped streaming file chunk" in stderr


def test_fstream_requests_error(
    publish_util, mock_server, inject_requests, mocker, capsys
):
    # inject a requests error, not a http error

    match = inject_requests.Match(path_suffix="/file_stream")
    inject_requests.add(match=match, requests_error=True)
    history = generate_history()
    publish_util(history=history)
    stdout, stderr = capsys.readouterr()
    assert "Dropped streaming file chunk" in stderr


def test_crdedupe_consecutive_offsets():
    fp = CRDedupeFilePolicy()
    console = {1: "a", 2: "a", 3: "a", 8: "a", 12: "a", 13: "a", 30: "a"}
    intervals = fp.get_consecutive_offsets(console)
    print(intervals)
    assert intervals == [[1, 3], [8, 8], [12, 13], [30, 30]]


@dataclass
class Chunk:
    data: str = None


def test_crdedupe_split_chunk():
    fp = CRDedupeFilePolicy()
    answer = [
        ("2020-08-25T20:38:36.895321 ", "this is my line of text\nsecond line\n"),
        ("ERROR 2020-08-25T20:38:36.895321 ", "this is my line of text\nsecond line\n"),
    ]
    test_data = [
        "2020-08-25T20:38:36.895321 this is my line of text\nsecond line\n",
        "ERROR 2020-08-25T20:38:36.895321 this is my line of text\nsecond line\n",
    ]
    for i, data in enumerate(test_data):
        c = Chunk(data=data)
        prefix, rest = fp.split_chunk(c)
        assert prefix == answer[i][0]
        assert rest == answer[i][1]


def test_crdedupe_process_chunks():
    fp = CRDedupeFilePolicy()
    sep = os.linesep
    files = {"output.log": None}

    # Test STDERR progress bar updates (\r lines) overwrite the correct offset.
    # Test STDOUT and STDERR normal messages get appended correctly.
    chunks = [
        Chunk(data=f"timestamp text{sep}"),
        Chunk(data=f"ERROR timestamp error message{sep}"),
        Chunk(data=f"ERROR timestamp progress bar{sep}"),
        Chunk(data=f"ERROR timestamp \rprogress bar update 1{sep}"),
        Chunk(data=f"ERROR timestamp \rprogress bar update 2{sep}"),
        Chunk(data=f"timestamp text{sep}text{sep}text{sep}"),
        Chunk(data=f"ERROR timestamp error message{sep}"),
    ]
    ret = fp.process_chunks(chunks)
    want = [
        {
            "offset": 0,
            "content": [
                "timestamp text\n",
                "ERROR timestamp error message\n",
                "ERROR timestamp progress bar update 2\n",
                "timestamp text\n",
                "timestamp text\n",
                "timestamp text\n",
                "ERROR timestamp error message\n",
            ],
        }
    ]
    print(f"\n{ret}")
    print(want)
    assert ret == want
    files["output.log"] = ret
    file_requests = list(
        file_stream_utils.split_files(files, max_bytes=util.MAX_LINE_BYTES)
    )
    assert 1 == len(file_requests)

    # Test that STDERR progress bar updates in next list of chunks still
    # maps to the correct offset.
    # Test that we can handle STDOUT progress bars (\r lines) as well.
    chunks = [
        Chunk(data=f"ERROR timestamp \rprogress bar update 3{sep}"),
        Chunk(data=f"ERROR timestamp \rprogress bar update 4{sep}"),
        Chunk(data=f"timestamp \rstdout progress bar{sep}"),
        Chunk(data=f"timestamp text{sep}"),
        Chunk(data=f"timestamp \rstdout progress bar update{sep}"),
    ]
    ret = fp.process_chunks(chunks)
    want = [
        {"offset": 2, "content": ["ERROR timestamp progress bar update 4\n"]},
        {"offset": 5, "content": ["timestamp stdout progress bar update\n"]},
        {"offset": 7, "content": ["timestamp text\n"]},
    ]
    print(f"\n{ret}")
    print(want)
    assert ret == want
    files["output.log"] = ret
    file_requests = list(
        file_stream_utils.split_files(files, max_bytes=util.MAX_LINE_BYTES)
    )
    assert 3 == len(file_requests)

    # Test that code handles final progress bar output and correctly
    # offsets any new progress bars.
    chunks = [
        Chunk(data=f"timestamp text{sep}"),
        Chunk(data=f"ERROR timestamp \rprogress bar final{sep}text{sep}text{sep}"),
        Chunk(data=f"ERROR timestamp error message{sep}"),
        Chunk(data=f"ERROR timestamp new progress bar{sep}"),
        Chunk(data=f"ERROR timestamp \rnew progress bar update 1{sep}"),
    ]
    ret = fp.process_chunks(chunks)
    want = [
        {"offset": 2, "content": ["ERROR timestamp progress bar final\n"]},
        {
            "offset": 8,
            "content": [
                "timestamp text\n",
                "ERROR timestamp text\n",
                "ERROR timestamp text\n",
                "ERROR timestamp error message\n",
                "ERROR timestamp new progress bar update 1\n",
            ],
        },
    ]
    print(f"\n{ret}")
    print(want)
    assert ret == want
    files["output.log"] = ret
    file_requests = list(
        file_stream_utils.split_files(files, max_bytes=util.MAX_LINE_BYTES)
    )
    assert 2 == len(file_requests)
