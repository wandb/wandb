"""
metric internal tests.
"""

from __future__ import print_function

import os
import pytest
import six
from six.moves import queue
import threading
import time
import shutil
import sys

import wandb
from wandb.proto import wandb_internal_pb2 as pb


def _gen_history():
    history = []
    history.append(dict(step=0, data=dict(v1=1, v2=2, v3="dog", mystep=1)))
    history.append(dict(step=1, data=dict(v1=3, v2=8, v3="cat", mystep=2)))
    history.append(dict(step=2, data=dict(v1=2, v2=3, v3="pizza", mystep=3)))
    return history


def _make_metrics(mitems):
    metrics = []
    for mitem in mitems:
        m = pb.MetricRecord()
        m.CopyFrom(mitem)
        metrics.append(m)
    return metrics


def test_metric_none(publish_util):
    history = _gen_history()
    ctx_util = publish_util(history=history)
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" not in ctx_util.config_wandb

    assert dict(v1=2, v2=3, v3="pizza", mystep=3, _step=2) == summary


def test_metric_step(publish_util):
    history = _gen_history()
    metrics = [
        pb.MetricRecord(glob_name="*", step_metric="mystep"),
    ]
    metrics = _make_metrics(metrics)
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" in config_wandb
    assert "mystep" in config_wandb["x_axis"]

    assert dict(v1=2, v2=3, v3="pizza", mystep=3, _step=2) == summary


def test_metric_max(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="v2")
    m1.summary.max = True
    metrics = _make_metrics([m1])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" not in config_wandb

    assert {
        "v1": 2,
        "v2": 3,
        "v2.max": 8,
        "v3": "pizza",
        "mystep": 3,
        "_step": 2,
    } == summary


def test_metric_min(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="v2")
    m1.summary.min = True
    metrics = _make_metrics([m1])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" not in config_wandb

    assert {
        "v1": 2,
        "v2": 3,
        "v2.min": 2,
        "v3": "pizza",
        "mystep": 3,
        "_step": 2,
    } == summary


def test_metric_min_str(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="v3")
    m1.summary.min = True
    metrics = _make_metrics([m1])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" not in config_wandb

    assert {"v1": 2, "v2": 3, "v3": "pizza", "mystep": 3, "_step": 2,} == summary


def test_metric_sum_none(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="v2")
    metrics = _make_metrics([m1])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" not in config_wandb

    assert {"v1": 2, "v2": 3, "v3": "pizza", "mystep": 3, "_step": 2,} == summary


def test_metric_mult(publish_util):
    history = _gen_history()
    m1 = pb.MetricRecord(name="mystep")
    m2 = pb.MetricRecord(name="v1", step_metric="mystep")
    m2.summary.max = True
    m3 = pb.MetricRecord(name="v2", step_metric="mystep")
    m3.summary.min = True
    metrics = _make_metrics([m1, m2, m3])
    ctx_util = publish_util(history=history, metrics=metrics)

    config_wandb = ctx_util.config_wandb
    summary = ctx_util.summary

    # TODO(jhr): remove these when UI updated
    assert "x_axis" in config_wandb
    assert "mystep" in config_wandb["x_axis"]

    assert {
        "v1": 2,
        "v1.max": 3,
        "v2": 3,
        "v2.min": 2,
        "v3": "pizza",
        "mystep": 3,
        "_step": 2,
    } == summary
