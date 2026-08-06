import queue
from unittest.mock import MagicMock

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal import handler, settings_static


def test_handle_sampled_history_empty(test_settings):
    result_q = queue.Queue()
    settings = test_settings({})
    hm = handler.HandleManager(
        settings=settings_static.SettingsStatic(dict(settings)),
        record_q=MagicMock(),
        result_q=result_q,
        stopped=MagicMock(),
        writer_q=MagicMock(),
        interface=MagicMock(),
    )

    record = pb.Record()
    record.request.sampled_history.CopyFrom(pb.SampledHistoryRequest())

    hm.handle(record)

    result = result_q.get()
    assert result.response.sampled_history_response.item == []
