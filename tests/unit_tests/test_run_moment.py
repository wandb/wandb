from __future__ import annotations

import pytest
from wandb.sdk.lib.run_moment import RunMoment


def test_run_moment_from_uri_valid():
    uri = "ans3bsax?_step=123"
    run_moment = RunMoment.from_uri(uri)
    assert run_moment.run == "ans3bsax"
    assert run_moment.metric == "_step"
    assert run_moment.value == 123


def test_run_moment_from_uri_invalid_format():
    uri = "ans3bsax?metric=123"
    with pytest.raises(ValueError):
        RunMoment.from_uri(uri)


def test_run_moment_from_uri_invalid_metric():
    uri = "ans3bsax?_metric=123"
    with pytest.raises(ValueError):
        RunMoment.from_uri(uri)


def test_run_moment_from_uri_invalid_value():
    uri = "ans3bsax?_step=abc"
    with pytest.raises(ValueError):
        RunMoment.from_uri(uri)


def test_run_moment_from_uri_invalid_path():
    uri = "ans3bsax/metric?_step=123"
    with pytest.raises(ValueError):
        RunMoment.from_uri(uri)


def test_run_moment_from_uri_invalid_params():
    uri = "ans3bsax?_step=123&metric=123"
    with pytest.raises(ValueError):
        RunMoment.from_uri(uri)


def test_run_moment_from_uri_invalid_fragment():
    uri = "ans3bsax?_step=123#metric=123"
    with pytest.raises(ValueError):
        RunMoment.from_uri(uri)


def test_run_moment_from_uri_invalid_scheme():
    uri = "http://ans3bsax?_step=123"
    with pytest.raises(ValueError):
        RunMoment.from_uri(uri)


def test_run_moment_invalid_direct_construction():
    with pytest.raises(ValueError):
        RunMoment(run=123, metric="loss", value="abcd")
