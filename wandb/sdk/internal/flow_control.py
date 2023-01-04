"""Flow Control.

States:
    FORWARDING
    PAUSING

New messages:
    pb.SenderMarkRequest    writer -> sender (empty message)
    pb.StatusReportRequest  sender -> writer (reports current sender progress)
    pb.SenderReadRequest    writer -> sender (requests read of transaction log)

Thresholds:
    Threshold_High_MaxOutstandingData       - When above this, stop sending requests to sender
    Threshold_Mid_StartSendingReadRequests - When below this, start sending read requests
    Threshold_Low_RestartSendingData       - When below this, start sending normal records

State machine:
    FORWARDING
      -> PAUSED if should_pause
    PAUSING
      -> FORWARDING if should_unpause
      -> PAUSING if should_recover
      -> PAUSING if should_quiesce

"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

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
    return record.control.flow_control


@dataclass
class StateContext:
    last_forwarded_offset: int = 0
    last_sent_offset: int = 0
    last_written_offset: int = 0


class FlowControl:
    _settings: SettingsStatic
    _forward_record_cb: Callable[["Record"], None]
    _write_record_cb: Callable[["Record"], int]
    _recover_records_cb: Callable[[int, int], None]

    _track_prev_written_offset: int
    _track_last_written_offset: int
    _track_last_forwarded_offset: int
    _track_first_unforwarded_offset: int
    # _track_last_flushed_offset: int
    # _track_recovering_requests: int

    _mark_forwarded_offset: int
    _mark_recovering_offset: int
    _mark_reported_offset: int

    _telemetry_obj: tpb.TelemetryRecord
    _telemetry_overflow: bool
    _fsm: fsm.FsmWithContext["Record", StateContext]

    def __init__(
        self,
        settings: SettingsStatic,
        forward_record: Callable[["Record"], None],
        write_record: Callable[["Record"], int],
        send_mark: Callable[[], None],
        recover_records: Callable[[int, int], None],
        _threshold_bytes_high: int = 4 * 1024 * 1024,  # 4MiB
        _threshold_bytes_mid: int = 2 * 1024 * 1024,  # 2MiB
        _threshold_bytes_low: int = 1 * 1024 * 1024,  # 1MiB
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

        # FSM definition
        state_forwarding = StateForwarding(
            forward_record=forward_record,
            send_mark=send_mark,
            threshold_pause=self._threshold_bytes_high,
        )
        state_pausing = StatePausing(
            forward_record=forward_record,
            recover_records=recover_records,
            threshold_recover=self._threshold_bytes_mid,
            threshold_forward=self._threshold_bytes_low,
        )
        self._fsm = fsm.FsmWithContext(
            states=[state_forwarding, state_pausing],
            table={
                StateForwarding: [
                    fsm.FsmEntry(
                        state_forwarding._should_pause,
                        StatePausing,
                        state_forwarding._pause,
                    ),
                ],
                StatePausing: [
                    fsm.FsmEntry(
                        state_pausing._should_unpause,
                        StateForwarding,
                        state_pausing._unpause,
                    ),
                    fsm.FsmEntry(
                        state_pausing._should_recover,
                        StatePausing,
                        state_pausing._recover,
                    ),
                    fsm.FsmEntry(
                        state_pausing._should_quiesce,
                        StatePausing,
                        state_pausing._quiesce,
                    ),
                ],
            },
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
        sent_offset = record.request.status_report.sent_offset
        self._mark_reported_offset = sent_offset

    def _forward_record(self, record: "Record") -> None:
        # DEBUG print("FORW REC", record.num)
        # print("FORW REC", record.num)
        self._forward_record_cb(record)
        # print("FORWARD: LASTFORWARD", self._track_last_forwarded_offset)

    def _update_prev_written_offset(self) -> None:
        self._track_prev_written_offset = self._track_last_written_offset

    def _write_record(self, record: "Record") -> None:
        offset = self._write_record_cb(record)
        # print("WROTE", offset, record)
        self._update_prev_written_offset()
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
        self._send_recover_read(inputs, read_last=True)
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
        self._send_recover_read(inputs, read_last=False)

    def _forward(self, inputs: "Record") -> None:
        self._send_recover_read(inputs, read_last=False)

    def flow(self, record: "Record") -> None:
        if self._debug:
            print("# FLOW", record.num)
            print("# FLOW-DEBUG", record)
        self._process_record(record)

        if not _is_local_record(record):
            self._write_record(record)
        else:
            self._update_prev_written_offset()

        self._fsm.input(record)


class StateShared:
    _context: StateContext

    def __init__(self) -> None:
        self._context = StateContext()

    def _update_written_offset(self, record: "Record") -> None:
        end_offset = record.control.end_offset
        if end_offset:
            self._context.last_written_offset = end_offset

    def _update_forwarded_offset(self) -> None:
        self._context.last_forwarded_offset = self._context.last_written_offset

    def _process(self, record: "Record") -> None:
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
        sent_offset = record.request.status_report.sent_offset
        self._context.last_sent_offset = sent_offset

    def on_exit(self, record: "Record") -> StateContext:
        return self._context

    def on_enter(self, record: "Record", context: StateContext) -> None:
        self._context = context

    @property
    def _behind_bytes(self) -> int:
        return self._context.last_forwarded_offset - self._context.last_sent_offset


class StateForwarding(StateShared):
    _forward_record: Callable[["Record"], None]
    _send_mark: Callable[[], None]
    _threshold_pause: int

    def __init__(
        self,
        forward_record: Callable[["Record"], None],
        send_mark: Callable[[], None],
        threshold_pause: int,
    ) -> None:
        super().__init__()
        self._forward_record = forward_record
        self._send_mark = send_mark
        self._threshold_pause = threshold_pause

    def _should_pause(self, record: "Record") -> bool:
        return self._behind_bytes >= self._threshold_pause

    def _pause(self, record: "Record") -> None:
        self._send_mark()

    def on_check(self, record: "Record") -> None:
        self._update_written_offset(record)
        self._process(record)
        if not _is_control_record(record):
            self._forward_record(record)
        self._update_forwarded_offset()


class StatePausing(StateShared):
    _forward_record: Callable[["Record"], None]
    _recover_records: Callable[[int, int], None]
    _threshold_recover: int
    _threshold_forward: int

    def __init__(
        self,
        forward_record: Callable[["Record"], None],
        recover_records: Callable[[int, int], None],
        threshold_recover: int,
        threshold_forward: int,
    ) -> None:
        super().__init__()
        self._forward_record = forward_record
        self._recover_records = recover_records
        self._threshold_recover = threshold_recover
        self._threshold_forward = threshold_forward

    def _should_unpause(self, record: "Record") -> bool:
        return self._behind_bytes < self._threshold_forward

    def _unpause(self, record: "Record") -> None:
        self._quiesce(record)

    def _should_recover(self, record: "Record") -> bool:
        return self._behind_bytes < self._threshold_recover

    def _recover(self, record: "Record") -> None:
        self._quiesce(record)

    def _should_quiesce(self, record: "Record") -> bool:
        return _is_local_record(record) and not _is_control_record(record)

    def _quiesce(self, record: "Record") -> None:
        start = self._context.last_forwarded_offset
        end = self._context.last_written_offset
        if start != end:
            self._recover_records(start, end)
        if _is_local_record(record) and not _is_control_record(record):
            self._forward_record(record)
        self._update_forwarded_offset()

    def on_check(self, record: "Record") -> None:
        self._update_written_offset(record)
        self._process(record)
