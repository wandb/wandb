from dataclasses import dataclass

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal import flow_control, settings_static


@dataclass
class Op:
    dispatch_delay: int = 0
    retire_delay: int = 0
    _dispatch_time: int = None
    _retire_time: int = None
    _record: int = None
    _offset: int = 0
    _length: int = 0


class RecordFactory:
    _done: bool
    _record_num: int
    _index: int

    def __init__(self, op_list=None):
        record = pb.Record()
        history = pb.HistoryRecord()
        record.history.CopyFrom(history)
        self._record = record
        self._record_num = 0
        self._index = 0
        self._op_list = op_list
        self._done = False
        self._assign_times()

    def _assign_times(self):
        if not self._op_list:
            return

        time = 0
        for r in self._op_list:
            time += r.dispatch_delay
            r._dispatch_time = time
            # r._retire_time = time + r.retire_delay

    def op_lookup_record(self, record):
        num = record.num
        if num == 0:
            return None
        return self._op_list[num - 1]

    def create_record(self, num=1):
        record = pb.Record()
        record.CopyFrom(self._record)
        record.history.step.num = num
        self._record_num += 1
        record.num = self._record_num
        return record

    def get_next_record(self):
        # are there any records scheduled to execute?
        # or any control records from the simulator

        if not self._op_list:
            self._done = True
            return None
        try:
            _ = self._op_list[self._index]
        except IndexError:
            self._done = True
            return None

        self._index += 1

        record = self.create_record()
        return record

    @property
    def done(self):
        if not self._op_list:
            self._done = True
        return self._done


class RecordSim:
    _time: int

    def __init__(self, f=None):
        self._offset = 0
        self._control_records = []
        self._f = f
        self._time = 0
        self._forward_time = 0
        self._forward_ops = []
        self._forward_index = 0
        self._debug = False
        # self._debug = True
        self._write_offset = 0
        self._send_offset = 0

    def _advance_time(self, tm):
        self._do_send_backlog(tm)
        self._time = tm

    def write_record(self, record):
        write_id = record.history.step.num
        write_len = write_id * 100
        self._offset += write_len
        # print("W:", record)
        if self._debug:
            print(f"W: {record.num} ({self._offset})")
        op = self._f.op_lookup_record(record)
        assert op
        op._offset = self._offset
        op._length = write_len
        self._write_offset = self._offset
        return self._offset

    def forward_record(self, record):
        write_id = record.history.step.num
        # print("F:", record)
        print("F:", write_id)
        op = self._f.op_lookup_record(record) or Op()
        op._record = record

        # update retire time
        if self._time > self._forward_time:
            self._forward_time = self._time
        self._forward_time += op.retire_delay
        op._retire_time = self._forward_time

        self._forward_ops.append(op)

    def _send_record(self, record):
        op = self._f.op_lookup_record(record) or Op()
        if self._debug:
            print(f"S: {record.num} ({op._offset})")

        if op._offset:
            assert self._send_offset + op._length == op._offset
            self._send_offset = op._offset

        request_type = record.request.WhichOneof("request_type")
        if request_type == "sender_mark":
            # print("GOT", record)
            mark_id = record.request.sender_mark.mark_id
            rec = pb.Record()
            req = pb.Request()
            mark_report = pb.SenderMarkReportRequest(mark_id=mark_id)
            req.sender_mark_report.CopyFrom(mark_report)
            rec.request.CopyFrom(req)
            self.respond(rec)
        elif request_type == "sender_read":
            if self._debug:
                print("GOT SENDREAD", record)
            assert self._send_offset == record.request.sender_read.start_offset
            self._send_offset = record.request.sender_read.end_offset

    def _do_send_backlog(self, future_time):
        index = self._forward_index
        current_time = self._time
        while True:
            if index >= len(self._forward_ops):
                break
            op = self._forward_ops[index]
            if future_time < op._retire_time:
                break
            # print("SEND", index, self._time, future_time, op._retire_time)
            self._send_record(op._record)
            index += 1
        self._forward_index = index
        if self._debug:
            print("C:", current_time)
            print("B:", len(self._forward_ops) - index)

    def _send_backlog_length(self):
        return len(self._forward_ops) - self._forward_index

    def respond(self, record):
        self._control_records.append(record)

    def ensure_flushed(self, record):
        pass

    def get_controls(self):
        res = self._control_records[:]
        self._control_records = []
        return res

    def process(self, rec, fc):
        if not rec:
            return None

        if self._debug:
            print(f"TIME: {self._time}")

        op = self._f.op_lookup_record(rec)

        next_time = op._dispatch_time
        self._advance_time(next_time)

        fc.send_with_flow_control(rec)

    def process_control_records(self, fc):
        self._do_send_backlog(self._time)
        for record in self._control_records:
            fc.send_with_flow_control(record)
        self._control_records = []

    def flush(self):
        # print("FLUSH")
        while self._send_backlog_length() > 0:
            next_time = self._time + 1
            self._advance_time(next_time)

    def check(self):
        print(f"write_offset: {self._write_offset}")
        print(f"send_offset: {self._send_offset}")
        assert self._write_offset == self._send_offset


def no_test_sim_flow():
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

        rec = f.create_record()
        flow.send_with_flow_control(rec)


def simulate(op_list):
    settings = settings_static.SettingsStatic({})

    f = RecordFactory(op_list=op_list)
    sim = RecordSim(f=f)
    flow = flow_control.FlowControl(
        settings=settings,
        write_record=sim.write_record,
        forward_record=sim.forward_record,
        ensure_flushed=sim.ensure_flushed,
        _threshold_bytes_high=1000,
        _threshold_bytes_mid=700,
        _threshold_bytes_low=400,
        _mark_granularity_bytes=200,
        _recovering_bytes_min=1400,
    )

    while not f.done:
        sim.process_control_records(fc=flow)
        record = f.get_next_record()
        sim.process(record, fc=flow)

    sim.flush()
    sim.check()


def test_slow_grow():
    """Generate records at twice the rate we send data."""
    op_list = []

    # grow req queue
    for _x in range(20):
        op_list.append(Op(dispatch_delay=1, retire_delay=2))

    # maintain req queue
    for _x in range(20):
        op_list.append(Op(dispatch_delay=1, retire_delay=1))

    # drain req queue
    for _x in range(20):
        op_list.append(Op(dispatch_delay=2, retire_delay=1))

    simulate(op_list)
    # TODO add fake time
    # assert about stuff
    # when data was sent?
    # transitions?


def test_forwarding():
    """Generate records at the same rate we send data."""
    pass


def test_pausing():
    """Generate records but never send data."""
    pass


def test_recovering():
    """Generate records at twice the rate we send data."""
    pass
