from __future__ import annotations

import queue
from collections import defaultdict
from unittest.mock import MagicMock

import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal import handler, sample, settings_static


def test_handle_bigint(test_settings):
    result_q = queue.Queue()
    settings = test_settings({})
    hm = handler.HandleManager(
        settings=settings_static.SettingsStatic(dict(settings)),
        record_q=MagicMock(),
        result_q=result_q,
        stopped=MagicMock(),
        writer_q=MagicMock(),
        interface=MagicMock(),
        context_keeper=MagicMock(),
    )

    sampled_history = pb.SampledHistoryRequest()
    request = pb.Request()
    request.sampled_history.CopyFrom(sampled_history)
    record = pb.Record()
    record.request.CopyFrom(request)

    bigint = 12379259919636694194
    hm._sampled_history = defaultdict(sample.UniformSampleAccumulator)
    hm._sampled_history["ints"].add(1)
    hm._sampled_history["floats"].add(2.2)
    hm._sampled_history["floats"].add(4.5)
    hm._sampled_history["bigint"].add(bigint)
    hm.handle(record)
    result = result_q.get()

    history = result.response.sampled_history_response
    sampled_history = {
        item.key: wandb.util.downsample(item.values_float or item.values_int, 40)
        for item in history.item
    }
    assert sampled_history["ints"] == [1]
    assert len(sampled_history["floats"]) == 2
    assert len(sampled_history["bigint"]) == 0
