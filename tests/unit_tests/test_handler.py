"""Tests for the legacy HandleManager.

HandleManager is now used only by the ``wandb sync --sync-tensorboard`` path
(see ``wandb/sync/sync.py``). During that flow TBWatcher publishes only
``config``/``files``/``history`` records into the handler, so the handler only
needs to dispatch those (plus the ``summary_record`` request that
``handle_history`` generates internally). This test exercises that exact path
and guards against re-introducing a dependency on the request/record handlers
that were removed for being unreachable on the sync path.
"""

import queue

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal import handler, settings_static


def _config_record():
    record = pb.Record()
    update = record.config.update.add()
    update.key = "lr"
    update.value_json = "0.1"
    return record


def _files_record():
    record = pb.Record()
    record.files.files.add().path = "media/images/foo.png"
    return record


def _history_record():
    record = pb.Record()
    for key, value_json in (("loss", "0.5"), ("_timestamp", "1234567890.0")):
        item = record.history.item.add()
        item.key = key
        item.value_json = value_json
    return record


def test_sync_tensorboard_handler_path(test_settings):
    """The records TBWatcher emits during sync flow through HandleManager."""
    writer_q = queue.Queue()
    settings = test_settings({})
    hm = handler.HandleManager(
        settings=settings_static.SettingsStatic(dict(settings)),
        record_q=queue.Queue(),
        result_q=queue.Queue(),
        stopped=False,
        writer_q=writer_q,
        interface=InterfaceQueue(record_q=queue.Queue()),
    )

    # Drive the handler exactly like SyncThread._send_tensorboard does.
    for record in (_config_record(), _files_record(), _history_record()):
        hm.handle(record)

    emitted = []
    while not writer_q.empty():
        emitted.append(writer_q.get())

    by_type = [r.WhichOneof("record_type") for r in emitted]
    # config/files/history are forwarded to the writer/sender ...
    assert "config" in by_type
    assert "files" in by_type
    assert "history" in by_type
    # ... and handle_history derives a summary update, sent as a request.
    requests = [r for r in emitted if r.WhichOneof("record_type") == "request"]
    assert [r.request.WhichOneof("request_type") for r in requests] == [
        "summary_record"
    ]
