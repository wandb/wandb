import json
from dataclasses import dataclass
from enum import Enum

import pytest
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal import flow_control, settings_static
from wandb.sdk.wandb_settings import Settings


class FlowTester:
    def __init__(self, high=1000, mid=500, low=250):
        self._offset = 0

        settings_obj = Settings()
        settings = settings_static.SettingsStatic(settings_obj.make_static())
        fc = flow_control.FlowControl(
            settings=settings,
            write_record=self._write_func,
            forward_record=self._forward_func,
            recover_records=self._recover_func,
            _threshold_bytes_high=high,
            _threshold_bytes_mid=mid,
            _threshold_bytes_low=low,
            _mark_granularity_bytes=50,
            _recovering_bytes_min=50,
        )
        self._fc = fc
        self._written = []
        self._forwarded = []
        self._recovered = []

    def _write_func(self, record):
        self._written.append(record)
        msg_size = json.loads(record.history.item[0].value_json)
        new_offset = self._offset + msg_size
        self._offset = new_offset
        return new_offset

    def _forward_func(self, record):
        self._forwarded.append(record)

    def _recover_func(self, record):
        self._recovered.append(record)

    def add(self, op, assert_state=None):
        self._fc.flow(op.record)

    @property
    def written(self):
        return self._written

    @property
    def forwarded(self):
        return self._forwarded

    @property
    def recovered(self):
        return self._recovered

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
        size: int = 0
        _id: int = 0

        @property
        def record(self):
            r = pb.Record()
            history = pb.HistoryRecord()
            r.history.CopyFrom(history)
            item = r.history.item.add()
            item.key = "size"
            item.value_json = json.dumps(self.size)
            return r

        def __eq__(self, other):
            return True

    def op(self, **kwargs):
        new_op = self.Op(**kwargs)
        self._op_unique += 1
        new_op._id = self._op_unique
        return new_op

    def is_op(self, record):
        record_type = record.WhichOneof("record_type")
        if record_type != "history":
            return False
        if record.history.item[0].key != "size":
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
def test_pause(flow_tester, ops_factory, size_offset, paused):
    ft = flow_tester(high=300, mid=200, low=100)
    ops = ops_factory()

    batch1 = [ops.op(size=100) for _ in range(2)]
    batch2 = [ops.op(size=(100 + size_offset))]
    batch3 = [ops.op(size=(100))]
    batch4 = [ops.op(size=100) for _ in range(2)]

    for op in batch1:
        ft.add(op)
        assert ft.state == State.FORWARDING
    assert batch1 == ft.written

    for op in batch2:
        ft.add(op)
        assert ft.state == State.FORWARDING
    assert batch1 + batch2 == ft.written

    for op in batch3:
        ft.add(op)
        assert ft.state == (State.PAUSING if paused else State.FORWARDING)
    assert batch1 + batch2 + batch3 == ft.written

    for op in batch4:
        ft.add(op)
        assert ft.state == State.PAUSING
    assert batch1 + batch2 + batch3 + batch4 == ft.written

    assert batch1 + batch2 + (batch3 if not paused else []) == list(
        filter(ops.is_op, ft.forwarded)
    )
    assert [] == ft.recovered
