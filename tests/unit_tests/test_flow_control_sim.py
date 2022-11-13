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
        self._offset = 0
        self._control_records = []

    def write_record(self, record):
        write_id = record.history.step.num
        self._offset += write_id * 100
        # print("W:", record)
        print("W:", write_id, self._offset)
        return self._offset

    def forward_record(self, record):
        write_id = record.history.step.num
        # print("F:", record)
        print("F:", write_id)
        request_type = record.request.WhichOneof("request_type")
        if request_type == "sender_mark":
            mark_id = record.request.sender_mark.mark_id
            rec = pb.Record()
            req = pb.Request()
            mark_report = pb.SenderMarkReportRequest(mark_id=mark_id)
            req.sender_mark_report.CopyFrom(mark_report)
            rec.request.CopyFrom(req)
            self.respond(rec)

    def respond(self, record):
        self._control_records.append(record)

    def ensure_flushed(self, record):
        pass

    def get_controls(self):
        res = self._control_records[:]
        self._control_records = []
        return res


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

        controls = sim.get_controls()
        for c in controls:
            print("C", c)

        rec = f.get_record()
        flow.send_with_flow_control(rec)
