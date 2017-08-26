#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_streaming_log
----------------------------------

Tests for the `StreamingLog` module.
"""
import pytest
from freezegun import freeze_time
from wandb.streaming_log import StreamingLog
import time
from .api_mocks import upload_logs
import signal

@freeze_time("1981-12-09 12:00:01")
@pytest.fixture
def streamer():
    return StreamingLog("test")

@freeze_time("1981-12-09 12:00:01")
def test_basic(streamer):
    streamer.write("Foo bar baz\n")
    streamer.write("Some progress line\r")
    assert len(streamer.line_buffer.lines) == 2

@freeze_time("1981-12-09 12:00:01")
def test_dedupe_progress(streamer):
    streamer.write("[&...]\r")
    streamer.write("[&&..]\r")
    streamer.write("[&&&.]\r")
    streamer.write("[&&&&]\r")
    assert len(streamer.line_buffer.lines) == 1
    assert streamer.line_buffer.line_number == 1

@freeze_time("1981-12-09 12:00:02")
def test_push_by_length(request_mocker, upload_logs, streamer):
    mock = upload_logs(request_mocker, "test")
    streamer.write("1\n")
    streamer.write("2\n")
    streamer.write("3\n")
    streamer.write("4\n")
    streamer.write("5\n")
    assert len(streamer.line_buffer.lines) == 0
    assert mock.called

@freeze_time("1981-12-09 12:00:01")
def test_rate_limit(request_mocker, upload_logs, streamer):
    streamer.write("1\n")
    streamer.write("2\n")
    streamer.write("3\n")
    streamer.write("4\n")
    streamer.write("5\n")
    assert len(streamer.line_buffer.lines) == 5

@freeze_time("1981-12-09 12:00:01")
def test_partial_lines(request_mocker, upload_logs, streamer):
    streamer.write("bing ")
    streamer.write("bong\n")
    streamer.write("..")
    streamer.write("..\n")
    assert len(streamer.line_buffer.lines) == 2
    with open(streamer.tempfile.name, "r") as temp:
        assert temp.read() == """bing bong
....
"""

def test_raise_on_status(request_mocker, upload_logs, streamer):
    mock = upload_logs(request_mocker, "test", status_code=500)
    assert not mock.called

def test_push_by_stale(request_mocker, upload_logs, streamer):
    mock = upload_logs(request_mocker, "test")
    streamer.write("boom\n")
    assert len(streamer.line_buffer.lines) == 0
    assert mock.called

def test_heartbeat(request_mocker, upload_logs, streamer):
    mock = upload_logs(request_mocker, "test")
    #TODO: gotta be a better way to test this
    signal.alarm(1)
    time.sleep(1.1)
    assert mock.called