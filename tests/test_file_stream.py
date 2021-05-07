"""
file_stream tests.
"""

from __future__ import print_function

import json


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


def assert_history(publish_util):
    history = generate_history()
    ctx_util = publish_util(history=history)

    converted_history = convert_history(history)
    assert ctx_util.history == converted_history


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
