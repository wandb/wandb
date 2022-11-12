import json

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal import flow_control, settings_static


class RecordFactory:
    def __init__(self):
        record = pb.Record()
        history = pb.HistoryRecord()
        record.history.CopyFrom(history)
        self._record = record

    def get_record(self, num=1):
        record = pb.Record()
        record.CopyFrom(self._record)
        record.history.step.num = num
        return record


class RecordSim:
    def __init__(self):
        pass

    def write_record(self, record):
        print("W:", record)

    def forward_record(self, record):
        print("F:", record)

    def ensure_flushed(self, record):
        pass


def test_sim_flow():
    settings = settings_static.SettingsStatic({})

    sim = RecordSim()
    flow = flow_control.FlowControl(
        settings=settings,
        write_record=sim.write_record,
        forward_record=sim.forward_record,
        ensure_flushed=sim.ensure_flushed,
    )

    f = RecordFactory()
    for _ in range(20):
        rec = f.get_record()
        flow.send_with_flow_control(rec)
