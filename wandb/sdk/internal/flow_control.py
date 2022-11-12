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
    PAUSED  - Writing records to disk and waiting for sender to drain
      -> READING when outstanding_data < Threshold_Mid_StartSendingReadRequests
    READING - Reading from disk and waiting for sender to drain
      -> FORWARDING when outstanding_data < Threshold_Low_RestartSendingData

"""

import enum
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb
from wandb.sdk.lib import fsm, telemetry

from .settings_static import SettingsStatic

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import Record

logger = logging.getLogger(__name__)


class _MarkType(enum.Enum):
    DEFAULT = 1
    PAUSE = 2


@dataclass
class _MarkInfo:
    block: int
    mark_type: _MarkType


@dataclass
class _WriteInfo:
    offset: int = 0
    block: int = 0


def _get_request_type(record: "Record") -> Optional[str]:
    record_type = record.WhichOneof("record_type")
    if record_type != "request":
        return None
    request_type = record.request.WhichOneof("request_type")
    return request_type


def _is_control_record(record: "Record") -> bool:
    request_type = _get_request_type(record)
    if request_type not in {"sender_mark_report"}:
        return False
    return True


class FlowControl:
    _settings: SettingsStatic
    _forward_record: Callable[[Any, "Record"], None]
    _write_record: Callable[[Any, "Record"], _WriteInfo]
    _ensure_flushed: Callable[[Any, int], None]
    _last_write: _WriteInfo
    _mark_dict: Dict[int, _MarkInfo]

    _telemetry_obj: tpb.TelemetryRecord
    _telemetry_overflow: bool
    _fsm: fsm.Fsm["Record"]

    def __init__(
        self,
        settings: SettingsStatic,
        forward_record: Callable[["Record"], None],
        write_record: Callable[["Record"], _WriteInfo],
        ensure_flushed: Callable[["int"], None],
    ) -> None:
        self._settings = settings
        self._forward_record = forward_record  # type: ignore
        self._write_record = write_record  # type: ignore
        self._ensure_flushed = ensure_flushed  # type: ignore

        # thresholds to define when to PAUSE, RESTART, FORWARDING
        self._threshold_block_high = 128  # 4MB
        self._threshold_block_mid = 64  # 2MB
        self._threshold_block_low = 16  # 512kB
        self._mark_granularity_blocks = 2  # 64kB

        # track last written request
        self._last_write = _WriteInfo()

        # periodic probes sent to the sender to find out how backed up we are
        self._mark_id = 0
        self._mark_id_sent = 0
        self._mark_id_reported = 0
        self._mark_dict = {}
        self._mark_block_sent = 0
        self._mark_block_reported = 0

        self._telemetry_obj = tpb.TelemetryRecord()
        self._telemetry_overflow = False

        # State machine definition
        fsm_table: fsm.FsmTable[Record] = {
            StateForwarding: [(self._should_pause, StatePaused)],
            StatePaused: [(self._should_read, StateReading)],
            StateReading: [(self._should_forward, StateForwarding)],
        }
        self._fsm = fsm.Fsm(
            states=[StateForwarding(self), StatePaused(self), StateReading(self)],
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
        mark_info = self._mark_dict.pop(mark_id)
        self._mark_id_reported = mark_id
        self._mark_reported_block = mark_info.block

    def _process_report_sender_position(self, record: "Record") -> None:
        pass

    def _send_mark(self, mark_type: _MarkType = _MarkType.DEFAULT) -> None:
        mark_id = self._mark_id
        self._mark_id += 1

        sender_mark = pb.SenderMarkRequest(mark_id=mark_id)
        request = pb.Request()
        request.sender_mark.CopyFrom(sender_mark)
        record = pb.Record()
        record.request.CopyFrom(request)
        self._forward_record(record)
        self._mark_id_sent = mark_id
        block = self._last_write.block
        self._mark_dict[mark_id] = _MarkInfo(block=block, mark_type=mark_type)
        self._mark_sent_block = block

    def _maybe_send_mark(self) -> None:
        """Send mark if we are writting the first record in a block."""
        # if self._last_block_end == self._written_block_end:
        #     return
        self._send_mark()

    def _maybe_request_read(self) -> None:
        pass
        # if we are paused
        # and more than one chunk has been written
        # and N time has elapsed
        # send message asking sender to read from last_read_offset to current_offset

    def _behind_blocks(self) -> int:
        # behind_ids = self._mark_id_sent - self._mark_id_reported
        behind_blocks = self._mark_block_sent - self._mark_block_reported
        # print(
        #     f"BEHIND id={behind_ids} b={behind_blocks} sent={self._mark_id_sent} rep{self._mark_id_reported}"
        # )
        return behind_blocks

    def flush(self) -> None:
        pass

    def _should_pause(self, data: "Record") -> bool:
        if self._behind_blocks() < self._threshold_block_high:
            return False
        return True

    def _should_read(self, data: "Record") -> bool:
        return False

    def _should_forward(self, data: "Record") -> bool:
        return False

    def send_with_flow_control(self, record: "Record") -> None:

        self._process_record(record)

        if not _is_control_record(record):
            self._write_record(record)

        self._fsm.run(record)


class StateForwarding:
    def __init__(self, flow: FlowControl) -> None:
        self._flow = flow

    def run(self, record: "Record") -> None:
        if _is_control_record(record):
            return
        self._flow._forward_record(record)
        self._flow._maybe_send_mark()


class StatePaused:
    def __init__(self, flow: FlowControl) -> None:
        self._flow = flow

    def enter(self, record: "Record") -> None:
        self._flow._telemetry_record_overflow()
        self._flow._send_mark()

    def run(self, record: "Record") -> None:
        if _is_control_record(record):
            return


class StateReading:
    def __init__(self, flow: FlowControl) -> None:
        self._flow = flow

    def run(self, record: "Record") -> None:
        if _is_control_record(record):
            return
