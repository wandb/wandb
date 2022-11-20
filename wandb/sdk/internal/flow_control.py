"""Flow Control.

States:

New messages:
    mark_position    writer -> sender (has an ID)
    report position  sender -> writer
    read data        writer -> sender (go read this data for me)

Thresholds:
    Threshold_High_MaxOutstandingData       - When above this, stop sending requests to sender
    Threshold_Mid_StartSendingReadRequests - When below this, start sending read requests
    Threshold_Low_RestartSendingData       - When below this, start sending normal records

State machine:
    FORWARDING  - Streaming every record to the sender in memory
      -> PAUSED when oustanding_data > Threshold_High_MaxOutstandingData
    PAUSING  - Writing records to disk and waiting for sender to drain
      -> RECOVERING when outstanding_data < Threshold_Mid_StartSendingReadRequests
    RECOVERING - Recovering from disk and waiting for sender to drain
      -> FORWARDING when outstanding_data < Threshold_Low_RestartSendingData


    should_pause:
        1) There is too much data written but waiting to be sent
            <--1--><--2--><--3--><--4--><--5--><--6-->
                  |                                  | track_last_written_offset
                  | mark_reported_offset

            track_last_written_offset - mark_reported_offset > pause_threshold_bytes


    should_recover:
        1) All forwarded data has been sent
            <--1--><--2--><--3--><--4--><--5--><--6-->
                  |                                  | track_last_written_offset
                  | track_last_forwarded_offset
                  | mark_forwarded_offset
                  | mark_reported_offset

            track_last_forwarded_offset == mark_forwarded_offset == mark_reported_offset
        2) Unsent data drops below a threshold (Optimization)
            <--1--><--2--><--3--><--4--><--5--><--6-->
                  |                                  | track_last_written_offset
                  | mark_reported_offset

            track_last_written_offset - mark_reported_offset < recover_threshold_bytes

    should_forward:
        1) Unread + Unsent data drops below a threshold
            <--1--><--2--><--3--><--4--><--5--><--6-->
                  |                                  | track_last_written_offset
                  | mark_reported_offset

"""

import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb
from wandb.sdk.lib import fsm, telemetry

from .settings_static import SettingsStatic

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import Record

logger = logging.getLogger(__name__)


def _get_request_type(record: "Record") -> Optional[str]:
    record_type = record.WhichOneof("record_type")
    if record_type != "request":
        return None
    request_type = record.request.WhichOneof("request_type")
    return request_type


def _is_local_record(record: "Record") -> bool:
    return record.control.local


def _is_control_record(record: "Record") -> bool:
    request_type = _get_request_type(record)
    if request_type not in {"sender_mark_report"}:
        return False
    return True


class FlowControl:
    _settings: SettingsStatic
    _forward_record_cb: Callable[[Any, "Record"], None]
    _write_record_cb: Callable[[Any, "Record"], int]
    _ensure_flushed_cb: Callable[[Any, int], None]

    _track_prev_written_offset: int
    _track_last_written_offset: int
    _track_last_forwarded_offset: int
    _track_first_unforwarded_offset: int
    # _track_last_flushed_offset: int
    # _track_recovering_requests: int

    _mark_granularity_bytes: int
    _mark_forwarded_offset: int
    _mark_recovering_offset: int
    _mark_reported_offset: int

    _telemetry_obj: tpb.TelemetryRecord
    _telemetry_overflow: bool
    _fsm: fsm.Fsm["Record"]

    def __init__(
        self,
        settings: SettingsStatic,
        forward_record: Callable[["Record"], None],
        write_record: Callable[["Record"], int],
        ensure_flushed: Callable[["int"], None],
        _threshold_bytes_high: int = 4 * 1024 * 1024,  # 4MiB
        _threshold_bytes_mid: int = 2 * 1024 * 1024,  # 2MiB
        _threshold_bytes_low: int = 1 * 1024 * 1024,  # 1MiB
        _mark_granularity_bytes: int = 64 * 1024,  # 64KiB
        _recovering_bytes_min: int = 32 * 1024,  # 32KiB
    ) -> None:
        self._settings = settings
        self._forward_record_cb = forward_record  # type: ignore
        self._write_record_cb = write_record  # type: ignore
        self._ensure_flushed_cb = ensure_flushed  # type: ignore

        # thresholds to define when to PAUSE, RESTART, FORWARDING
        self._threshold_bytes_high = _threshold_bytes_high
        self._threshold_bytes_mid = _threshold_bytes_mid
        self._threshold_bytes_low = _threshold_bytes_low
        # self._threshold_bytes_high = 1000
        # self._threshold_block_mid = 64  # 2MB
        # self._threshold_block_low = 16  # 512kB
        self._mark_granularity_bytes = _mark_granularity_bytes
        self._recovering_bytes_min = _recovering_bytes_min

        self._track_last_read_offset = 0
        self._track_last_unread_offset = 0
        # self._track_last_unread_offset_previous_block = 0

        # how much to collect while pausing before going to reading
        # self._threshold_pausing_chunk = 100

        # should we toggle between recovering and pausing?  maybe?

        # track last written request
        self._track_prev_written_offset = 0
        self._track_last_written_offset = 0
        self._track_last_forwarded_offset = 0
        self._track_last_recovering_offset = 0

        self._track_first_unforwarded_offset = 0

        # periodic probes sent to the sender to find out how backed up we are
        self._mark_forwarded_offset = 0
        self._mark_recovering_offset = 0
        self._mark_reported_offset = 0

        self._telemetry_obj = tpb.TelemetryRecord()
        self._telemetry_overflow = False

        self._debug = False
        # self._debug = True

        # State machine definition
        fsm_table: fsm.FsmTable[Record] = {
            StateForwarding: [fsm.FsmEntry(self._should_pause, StatePausing)],
            StatePausing: [
                fsm.FsmEntry(self._should_quiesce, StateForwarding, self._quiesce),
                fsm.FsmEntry(self._should_recover, StateRecovering),
            ],
            StateRecovering: [
                fsm.FsmEntry(self._should_quiesce, StateForwarding, self._quiesce),
                fsm.FsmEntry(self._should_forward, StateForwarding, self._quiesce),
                fsm.FsmEntry(self._should_reqread, StateRecovering, self._reqread),
            ],
        }
        self._fsm = fsm.Fsm(
            states=[StateForwarding(self), StatePausing(self), StateRecovering(self)],
            table=fsm_table,
        )

    def _telemetry_record_overflow(self) -> None:
        if self._telemetry_overflow:
            return
        self._telemetry_overflow = True
        with telemetry.context(obj=self._telemetry_obj) as tel:
            tel.feature.flow_control_overflow = True
        record = pb.Record()
        record.telemetry.CopyFrom(self._telemetry_obj)
        self._forward_record(record)

    def _process_record(self, record: "Record") -> None:
        request_type = _get_request_type(record)
        if request_type == "sender_mark_report":
            self._process_sender_mark_report(record)

    def _process_sender_mark_report(self, record: "Record") -> None:
        mark_id = record.request.sender_mark_report.mark_id
        self._mark_reported_offset = mark_id

    def _process_report_sender_position(self, record: "Record") -> None:
        pass

    def _forward_record(self, record: "Record") -> None:
        self._forward_record_cb(record)
        # print("FORWARD: LASTFORWARD", self._track_last_forwarded_offset)

    def _write_record(self, record: "Record") -> None:
        offset = self._write_record_cb(record)
        self._track_prev_written_offset = self._track_last_written_offset
        self._track_last_written_offset = offset

    def _ensure_flushed(self, end_offset: int) -> None:
        if self._ensure_flushed_cb:
            self._ensure_flushed_cb(end_offset)

    def _send_recovering_read(self, start: int, end: int) -> None:
        record = pb.Record()
        request = pb.Request()
        # last_write_offset = self._track_last_written_offset
        sender_read = pb.SenderReadRequest(start_offset=start, end_offset=end)
        request.sender_read.CopyFrom(sender_read)
        record.request.CopyFrom(request)
        self._ensure_flushed(end)
        self._forward_record(record)
        # print("MARK", last_write_offset)

    def _send_mark(self) -> None:
        record = pb.Record()
        request = pb.Request()
        last_write_offset = self._track_last_written_offset
        sender_mark = pb.SenderMarkRequest(mark_id=last_write_offset)
        request.sender_mark.CopyFrom(sender_mark)
        record.request.CopyFrom(request)
        self._forward_record(record)
        # print("MARK", last_write_offset)

    def _maybe_send_mark(self) -> None:
        """Send mark if we are writting the first record in a block."""
        if (
            self._track_last_forwarded_offset
            >= self._mark_forwarded_offset + self._mark_granularity_bytes
        ):
            self._send_mark()

    def _maybe_request_read(self) -> None:
        pass
        # if we are paused
        # and more than one chunk has been written
        # and N time has elapsed
        # send message asking sender to read from last_read_offset to current_offset

    def _forwarded_bytes_behind(self) -> int:
        behind_bytes = self._track_last_forwarded_offset - self._mark_reported_offset
        return behind_bytes

    def _recovering_bytes_behind(self) -> int:
        behind_bytes = (
            self._track_last_written_offset - self._track_last_recovering_offset
        )
        return behind_bytes

    def flush(self) -> None:
        pass

    def _should_pause(self, inputs: "Record") -> bool:
        # print(
        #     f"SHOULD_PAUSE: {self._forwarded_bytes_behind()} {self._threshold_bytes_high}"
        # )
        if self._forwarded_bytes_behind() >= self._threshold_bytes_high:
            # print("PAUSE", self._track_last_forwarded_offset)
            return True
        # print(f"NOT_PAUSE: {self._behind_bytes()} {self._threshold_bytes_high}")
        return False

    def _should_recover(self, inputs: "Record") -> bool:
        # print(
        #     f"SHOULD_RECOVER1: {self._track_last_forwarded_offset} {self._mark_forwarded_offset} {self._mark_reported_offset}"
        # )
        if (
            self._track_last_forwarded_offset
            == self._mark_forwarded_offset
            == self._mark_reported_offset
        ):
            # print("RECOVER1")
            return True
        # print(
        #     f"SHOULD_RECOVER2: {self._forwarded_bytes_behind()} {self._threshold_bytes_mid}"
        # )
        if self._forwarded_bytes_behind() <= self._threshold_bytes_mid:
            # print("RECOVER2")
            return True
        return False

    def _should_forward(self, inputs: "Record") -> bool:
        # print(
        #     f"SHOULD_FORWARD: {self._recovering_bytes_behind()} {self._threshold_bytes_low}"
        # )
        if self._recovering_bytes_behind() < self._threshold_bytes_low:
            # print("FORWARD")
            return True
        return False

    def _should_quiesce(self, inputs: "Record") -> bool:
        record = inputs
        return _is_local_record(record)

    def _should_reqread(self, inputs: "Record") -> bool:
        # do we have a large enough read to do
        behind = self._recovering_bytes_behind()
        # print("BEHIND", behind)
        if behind < self._recovering_bytes_min:
            # print("NOTENOUGH")
            return False

        # make sure we dont already have a read in progress
        if (
            self._mark_recovering_offset
            and self._mark_reported_offset < self._mark_recovering_offset
        ):
            # print("ALREADY SENT")
            return False
        return True

    def _doread(self, record: "Record", read_last: bool=False) -> None:
        # issue read for anything written but not forwarded yet
        # print("Qr:", self._track_last_recovering_offset)
        # print("Qf:", self._track_last_forwarded_offset)
        # print("Qp:", self._track_prev_written_offset)
        # print("Qw:", self._track_last_written_offset)

        start = max(
            self._track_last_recovering_offset, self._track_last_forwarded_offset
        )
        end = self._track_last_written_offset if read_last else self._track_prev_written_offset
        # print("QUIESCE", start, end, record)
        if end > start:
            self._send_recovering_read(start, end)

        self._track_last_recovering_offset = end

    def _reqread(self, inputs: "Record") -> None:
        self._doread(inputs, read_last=True)
        self._send_mark()
        self._mark_recovering_offset = self._track_last_written_offset
        if self._debug:
            print("REQREAD", self._track_last_written_offset)

    def _quiesce(self, inputs: "Record") -> None:
        self._doread(inputs)

    def send_with_flow_control(self, record: "Record") -> None:
        self._process_record(record)

        if not _is_control_record(record) and not _is_local_record(record):
            self._write_record(record)

        self._fsm.input(record)


class StateForwarding:
    def __init__(self, flow: FlowControl) -> None:
        self._flow = flow

    def on_state(self, record: "Record") -> None:
        if _is_control_record(record):
            return
        self._flow._forward_record(record)
        self._flow._track_last_forwarded_offset = self._flow._track_last_written_offset
        self._flow._maybe_send_mark()


class StatePausing:
    def __init__(self, flow: FlowControl) -> None:
        self._flow = flow

    def on_enter(self, record: "Record") -> None:
        # print("ENTER PAUSE")
        self._flow._telemetry_record_overflow()
        self._flow._send_mark()
        self._flow._mark_forwarded_offset = self._flow._track_last_written_offset
        self._flow._track_first_unforwarded_offset = (
            self._flow._track_last_written_offset
        )
        # print("ENTER PAUSE", self._flow._mark_forwarded_offset)


class StateRecovering:
    def __init__(self, flow: FlowControl) -> None:
        self._flow = flow

    def on_enter(self, record: "Record") -> None:
        # print("ENTER RECOV", self._flow._track_last_forwarded_offset)
        self._flow._track_last_recovering_offset = (
            self._flow._track_last_forwarded_offset
        )
        self._flow._mark_recovering_offset = 0
