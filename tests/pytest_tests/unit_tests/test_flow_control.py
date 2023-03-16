import json
import time
from dataclasses import dataclass
from enum import Enum

import pytest
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal import flow_control, settings_static
from wandb.sdk.lib import proto_util
from wandb.sdk.wandb_settings import Settings


class FlowTester:
    def __init__(self, high=1000, mid=500, low=250):
        self._record_num = 0
        self._offset = 0

        settings_obj = Settings()
        settings = settings_static.SettingsStatic(settings_obj.make_static())
        fc = flow_control.FlowControl(
            settings=settings,
            write_record=self._write_func,
            forward_record=self._forward_func,
            pause_marker=self._pause_marker_func,
            recover_records=self._recover_func,
            _threshold_bytes_high=high,
            _threshold_bytes_mid=mid,
            _threshold_bytes_low=low,
        )
        self._fc = fc
        self._written = []
        self._forwarded = []
        self._sendmarks = []
        self._recovered = []

    def _write_func(self, record):
        self._record_num += 1
        proto_util._assign_record_num(record, self._record_num)
        self._written.append(record)
        msg_size = OpsFactory.get_op_size(record)
        new_offset = self._offset + msg_size
        self._offset = new_offset
        proto_util._assign_end_offset(record, new_offset)
        return new_offset

    def _forward_func(self, record):
        self._forwarded.append(record)

    def _pause_marker_func(self):
        self._sendmarks.append(True)

    def _recover_func(self, start, end):
        self._recovered.append((start, end))

    def add(self, op, assert_state=None):
        record = op.record
        if OpsFactory.is_op(record):
            self._write_func(record)
        self._fc.flow(record)

    @property
    def written(self):
        data = self._written
        self._written = []
        return data

    @property
    def forwarded(self):
        data = self._forwarded
        self._forwarded = []
        return data

    @property
    def forwarded_ops(self):
        return list(filter(OpsFactory.is_op, self.forwarded))

    @property
    def recovered(self):
        data = self._recovered
        self._recovered = []
        return data

    @property
    def state(self):
        state_list = self._fc._fsm._states
        state_obj = self._fc._fsm._state
        index = state_list.index(state_obj)
        return State(index)


@pytest.fixture
def flow_tester():
    def make_tester(high=None, mid=None, low=None):
        ft = FlowTester(high=high, mid=mid, low=low)
        return ft

    yield make_tester


class OpsFactory:
    def __init__(self):
        self._op_unique = 100

    @dataclass
    class Op:
        op_type: str = "data"
        size: int = 0
        offset: int = 0
        _id: int = 0

        @staticmethod
        def _add_item(history, key, val):
            item = history.item.add()
            item.key = key
            item.value_json = json.dumps(val)

        def _get_data_record(self):
            r = pb.Record()
            history = pb.HistoryRecord()
            r.history.CopyFrom(history)
            self._add_item(r.history, "op", "data")
            self._add_item(r.history, "size", self.size)
            self._add_item(r.history, "id", self._id)
            return r

        def _get_inform_record(self):
            status_report = pb.StatusReportRequest(
                record_num=0,
                sent_offset=self.offset,
            )
            status_time = time.time()
            status_report.sync_time.FromMicroseconds(int(status_time * 1e6))
            request = pb.Request()
            request.status_report.CopyFrom(status_report)
            record = pb.Record()
            record.control.local = True
            record.control.flow_control = True
            record.request.CopyFrom(request)
            return record

        @property
        def record(self):
            if self.op_type == "data":
                return self._get_data_record()
            if self.op_type == "inform":
                return self._get_inform_record()
            raise AssertionError(f"unknown op_type: {self.op_type}")

        def __eq__(self, other):
            other_id = OpsFactory.get_op_id(other)
            return self._id == other_id

    def op(self, **kwargs):
        new_op = self.Op(**kwargs)
        self._op_unique += 1
        new_op._id = self._op_unique
        return new_op

    @staticmethod
    def get_op_size(record):
        assert OpsFactory.is_op(record)
        msg_size = json.loads(record.history.item[1].value_json)
        return msg_size

    @staticmethod
    def get_op_id(record):
        if not OpsFactory.is_op(record):
            return None
        msg_id = json.loads(record.history.item[2].value_json)
        return msg_id

    @staticmethod
    def is_op(record):
        record_type = record.WhichOneof("record_type")
        if record_type != "history":
            return False
        if record.history.item[0].key != "op":
            return False
        op_type = json.loads(record.history.item[0].value_json)
        if op_type != "data":
            return False
        return True


@pytest.fixture
def ops_factory():
    def make_factory():
        factory = OpsFactory()
        return factory

    yield make_factory


class State(Enum):
    FORWARDING = 0
    PAUSING = 1
    RECOVERING = 2


@pytest.mark.parametrize(
    "size_offset, paused",
    [
        (-1, False),
        (0, True),
        (1, True),
        (100000, True),
    ],
)
def test_forward_to_pause(flow_tester, ops_factory, size_offset, paused):
    ft = flow_tester(high=300, mid=200, low=100)
    ops = ops_factory()

    batch_prep = [ops.op(size=100) for _ in range(2)]
    batch_test1 = [ops.op(size=(100 + size_offset))]
    batch_test2 = [ops.op(size=100)]
    batch_post = [ops.op(size=100) for _ in range(2)]

    for op in batch_prep:
        ft.add(op)
        assert ft.state == State.FORWARDING
    assert batch_prep == ft.written
    assert batch_prep == ft.forwarded_ops

    for op in batch_test1:
        ft.add(op)
        assert ft.state == (State.PAUSING if paused else State.FORWARDING)
    assert batch_test1 == ft.written
    assert batch_test1 == ft.forwarded_ops

    for op in batch_test2:
        ft.add(op)
        assert ft.state == State.PAUSING
    assert batch_test2 == ft.written
    assert (batch_test2 if not paused else []) == ft.forwarded_ops

    for op in batch_post:
        ft.add(op)
        assert ft.state == State.PAUSING
    assert batch_post == ft.written
    assert [] == ft.forwarded_ops

    assert [] == ft.recovered


def prep_pause(ft, ops):
    batch_prep1 = [ops.op(size=100) for _ in range(2)]
    batch_prep2 = [ops.op(size=100)]

    for op in batch_prep1:
        ft.add(op)
        assert ft.state == State.FORWARDING
    assert batch_prep1 == ft.written
    assert batch_prep1 == ft.forwarded_ops

    for op in batch_prep2:
        ft.add(op)
        assert ft.state == State.PAUSING
    assert batch_prep2 == ft.written
    assert batch_prep2 == ft.forwarded_ops


@pytest.mark.parametrize(
    "size_offset, forwarding",
    [
        (-1, False),
        (0, True),
        (1, True),
    ],
)
def test_pause_to_forward(flow_tester, ops_factory, size_offset, forwarding):
    ft = flow_tester(high=300, mid=200, low=100)
    ops = ops_factory()

    batch_test1 = [ops.op(op_type="inform", offset=201 + size_offset)]
    batch_test2 = [ops.op(size=50)]

    prep_pause(ft, ops)

    for op in batch_test1:
        ft.add(op)
        assert ft.state == State.FORWARDING if forwarding else State.PAUSING
    assert [] == ft.forwarded_ops
    assert [] == ft.written
    assert [] == ft.recovered

    for op in batch_test2:
        ft.add(op)
        assert ft.state == State.FORWARDING if forwarding else State.PAUSING
    assert batch_test2 == ft.written
    assert batch_test2 if forwarding else [] == ft.forwarded_ops
    assert ([] if forwarding else [(300, 350)]) == ft.recovered


def test_forwarding_mark():
    pass


def test_forwarding_pause_mark():
    pass
