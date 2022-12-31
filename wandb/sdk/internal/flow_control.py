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
from typing import TYPE_CHECKING, Callable, Optional

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb
from wandb.sdk.lib import fsm, telemetry

from .settings_static import SettingsStatic

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import Record

logger = logging.getLogger(__name__)


def _get_record_type(record: "Record") -> Optional[str]:
    record_type = record.WhichOneof("record_type")
    return record_type


def _get_request_type(record: "Record") -> Optional[str]:
    record_type = record.WhichOneof("record_type")
    if record_type != "request":
        return None
    request_type = record.request.WhichOneof("request_type")
    return request_type


def _is_local_record(record: "Record") -> bool:
    return record.control.local


def _is_control_record(record: "Record") -> bool:
    return record.control.flow_control


class FlowControl:
    _settings: SettingsStatic
    _forward_record_cb: Callable[["Record"], None]
    _write_record_cb: Callable[["Record"], int]
    _recover_records_cb: Callable[[int, int], None]

    _track_wake_offset: int
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
        recover_records: Callable[[int, int], None],
        _threshold_bytes_high: int = 4 * 1024 * 1024,  # 4MiB
        _threshold_bytes_mid: int = 2 * 1024 * 1024,  # 2MiB
        _threshold_bytes_low: int = 1 * 1024 * 1024,  # 1MiB
        _mark_granularity_bytes: int = 64 * 1024,  # 64KiB
        _recovering_bytes_min: int = 32 * 1024,  # 32KiB
    ) -> None:
        self._settings = settings
        self._forward_record_cb = forward_record
        self._write_record_cb = write_record
        self._recover_records_cb = recover_records

        # thresholds to define when to PAUSE, RESTART, FORWARDING
        if settings._ram_buffer:
            self._threshold_bytes_high = settings._ram_buffer
            self._threshold_bytes_mid = settings._ram_buffer // 2
            self._threshold_bytes_low = settings._ram_buffer // 4
        else:
            self._threshold_bytes_high = _threshold_bytes_high
            self._threshold_bytes_mid = _threshold_bytes_mid
            self._threshold_bytes_low = _threshold_bytes_low
        self._mark_granularity_bytes = _mark_granularity_bytes
        self._recovering_bytes_min = _recovering_bytes_min

        self._track_last_read_offset = 0
        self._track_last_unread_offset = 0
        # self._track_last_unread_offset_previous_block = 0

        # how much to collect while pausing before going to reading
        # self._threshold_pausing_chunk = 100

        # should we toggle between recovering and pausing?  maybe?

        # track last written request
        self._track_wake_offset = 0
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
            StateForwarding: [
                fsm.FsmEntry(self._should_quiesce, StateForwarding),
                fsm.FsmEntry(self._should_pause, StatePausing, self._do_pause),
            ],
            StatePausing: [
                fsm.FsmEntry(self._should_quiesce, StateForwarding, self._do_quiesce),
                fsm.FsmEntry(self._should_unpause, StateForwarding, self._do_unpause),
                fsm.FsmEntry(self._should_recover, StateRecovering, self._do_recover),
            ],
            StateRecovering: [
                fsm.FsmEntry(self._should_quiesce, StateForwarding, self._do_quiesce),
                fsm.FsmEntry(self._should_forward, StateForwarding, self._do_quiesce),
                fsm.FsmEntry(self._should_recover, StateRecovering, self._do_recover),
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
        if not request_type:
            return
        process_str = f"_process_{request_type}"
        process_handler: Optional[Callable[["pb.Record"], None]] = getattr(
            self, process_str, None
        )
        if not process_handler:
            return
        process_handler(record)

    def _process_status_report(self, record: "Record") -> None:
        send_offset = record.request.status_report.send_offset
        self._mark_reported_offset = send_offset

    def _forward_record(self, record: "Record") -> None:
        # DEBUG print("FORW REC", record.num)
        # print("FORW REC", record.num)
        self._forward_record_cb(record)
        # print("FORWARD: LASTFORWARD", self._track_last_forwarded_offset)

    def _write_record(self, record: "Record") -> None:
        offset = self._write_record_cb(record)
        # print("WROTE", offset, record)
        self._track_prev_written_offset = self._track_last_written_offset
        self._track_last_written_offset = offset

    def _send_mark(self) -> None:
        record = pb.Record()
        request = pb.Request()
        # last_write_offset = self._track_last_written_offset
        sender_mark = pb.SenderMarkRequest()
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
        if self._track_last_recovering_offset == 0:
            return 0
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
            # print("PAUSE", self._track_last_forwarded_offset, inputs.num)
            if self._debug:
                print("# FSM :: should_pause")
            return True
        # print(f"NOT_PAUSE: {self._behind_bytes()} {self._threshold_bytes_high}")
        return False

    def _should_unpause(self, inputs: "Record") -> bool:
        bytes_behind = self._forwarded_bytes_behind()
        if bytes_behind <= self._threshold_bytes_low:
            return True
        return False

    def _should_forward(self, inputs: "Record") -> bool:
        # print(
        #     f"SHOULD_FORWARD: {self._recovering_bytes_behind()} {self._threshold_bytes_low}"
        # )
        bytes_behind = max(
            self._forwarded_bytes_behind(), self._recovering_bytes_behind()
        )
        bytes_behind = self._recovering_bytes_behind()
        # print("SHOULD FORWARD", bytes_behind, self._forwarded_bytes_behind(), self._recovering_bytes_behind(), inputs)
        if bytes_behind <= self._threshold_bytes_low:
            # print("FORWARD")
            if self._debug:
                print("# FSM :: should forward")
            return True
        return False

    def _should_quiesce(self, inputs: "Record") -> bool:
        record = inputs
        quiesce = _is_local_record(record) and not _is_control_record(record)
        if quiesce and self._debug:
            print("# FSM :: should quiesce")
        return quiesce

    def _should_recover(self, inputs: "Record") -> bool:
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
        # print("# FSM recover")

        if self._debug:
            print("# FSM :: should recover")
        return True

    def _send_recover_read(self, record: "Record", read_last: bool = False) -> None:
        # issue read for anything written but not forwarded yet
        # print("Qr:", self._track_last_recovering_offset)
        # print("Qf:", self._track_last_forwarded_offset)
        # print("Qp:", self._track_prev_written_offset)
        # print("Qw:", self._track_last_written_offset)
        # TODO(mempressure): only read if there is stuff to read

        start = max(
            self._track_last_recovering_offset, self._track_last_forwarded_offset
        )
        end = (
            self._track_last_written_offset
            if read_last
            else self._track_prev_written_offset
        )
        # print("RECOVERREAD", start, end, read_last)
        if self._debug:
            print("DOREAD", start, end, record)

        if end > start:
            self._recover_records_cb(start, end)

        self._track_last_recovering_offset = end

    def _do_recover(self, inputs: "Record") -> None:
        self._send_recover_read(inputs, read_last=False)
        self._send_mark()
        self._mark_recovering_offset = self._track_last_written_offset
        if self._debug:
            print("REQREAD", self._track_last_written_offset)

    def _do_pause(self, inputs: "Record") -> None:
        pass

    def _do_unpause(self, inputs: "Record") -> None:
        self._send_recover_read(inputs, read_last=True)

    def _do_quiesce(self, inputs: "Record") -> None:
        # TODO(mempressure): can quiesce ever be a record?
        self._send_recover_read(inputs, read_last=True)

    def _forward(self, inputs: "Record") -> None:
        self._send_recover_read(inputs, read_last=False)

    def flow(self, record: "Record") -> None:
        if self._debug:
            print("# FLOW", record.num)
            print("# FLOW-DEBUG", record)
        self._process_record(record)

        if not _is_local_record(record):
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
        # print("IN(pausing)")
        # print("ENTER PAUSE")
        self._flow._telemetry_record_overflow()
        self._flow._send_mark()

        # we want to make sure we dont pause forever
        self._flow._track_wake_offset = self._flow._track_last_written_offset
        # print("WAKESET", self._flow._track_wake_offset)

        self._flow._mark_forwarded_offset = self._flow._track_last_written_offset
        self._flow._track_first_unforwarded_offset = (
            self._flow._track_last_written_offset
        )
        # print("ENTER PAUSE", self._flow._mark_forwarded_offset)

    # def on_exit(self, record: "Record") -> None:
    #     print("OUT(pausing)", record)


class StateRecovering:
    def __init__(self, flow: FlowControl) -> None:
        self._flow = flow

    def on_enter(self, record: "Record") -> None:
        # print("ENTER RECOV", self._flow._track_last_forwarded_offset)

        # BUG - BUG - BUG
        # self._flow._track_last_recovering_offset = (
        #     self._flow._track_last_forwarded_offset
        # )
        self._flow._mark_recovering_offset = 0
