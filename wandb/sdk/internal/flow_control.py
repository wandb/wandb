"""Flow Control.

    States
    ------
    ACTIVE = Streaming every record to the sender
    PAUSED = Collecting requests to the current block
    READING = Managing the read queue of the sender
    RESTARTING = Transitionary state waiting for request
                 completing a block

    Examples
    --------
    |   Block1   |   Block2   |   Block3   |   Block4   |
    |      < 0><  1 ><-2-><--3-->          |            |

inmem col: 0        col 1,2       col 3

Q: can we only keep track of starting block... it will make things easier

we might be able to use the next starting block, which is actually want we probably want
but if we used next starting block we might need to look at startingblock+offset to know that the previous request was in the
fully in the previous block (ie, offset would have to be zero)


New messages:
  mark_position    writer -> sender (has an ID)
  report position  sender -> writer
  read data        writer -> sender (go read this data for me)


Thresholds:
    ThresholdMaxOutstandingData       - When above this, stop sending requests to sender
    ThresholdStartSendingReadRequests - When below this, start sending read requests
    ThresholdRestartSendingData       - When below this, start sending normal records

"""

import enum
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from wandb.proto import wandb_internal_pb2 as pb

from .settings_static import SettingsStatic

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import Record

logger = logging.getLogger(__name__)


class _SendState(enum.Enum):
    ACTIVE = 1
    PAUSED = 2
    READING = 3
    RESTARTING = 4


class _MarkType(enum.Enum):
    DEFAULT = 1
    PAUSE = 2


@dataclass
class _MarkInfo:
    block: int
    mark_type: _MarkType


@dataclass
class _WriteInfo:
    offset: int
    block: int


class FlowControl:
    _settings: SettingsStatic
    _forward_record: Callable[["Record"], None]
    _write_record: Callable[["Record"], _WriteInfo]
    _ensure_flushed: Callable[[int], None]

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

        # thresholds to define when to PAUSE and RESTART
        self._threshold_block_high = 8
        self._threshold_block_low = 4

        # collection of requests ending in current block
        self._collection_block = None
        self._collection_records = []

        # track last written request
        self._written_offset = None
        self._written_block_start = 0
        self._written_block_end = 0

        # state machine ACTIVE -> PAUSED -> RESTARTING -> ACTIVE ...
        self._state = _SendState.ACTIVE

        # periodic probes sent to the sender to find out how backed up we are
        self._mark_id = 0
        self._mark_id_sent = 0
        self._mark_id_reported = 0
        self._mark_dict = {}
        self._mark_block_sent = 0
        self._mark_block_reported = 0

    def _get_request_type(self, record) -> str:
        record_type = record.WhichOneof("record_type")
        if record_type != "request":
            return None
        request_type = record.request.WhichOneof("request_type")
        return request_type

    def _is_control_record(self, record) -> bool:
        request_type = self._get_request_type(record)
        if request_type not in {"sender_mark_report"}:
            return False
        return True

    def _process_record(self, record) -> None:
        request_type = self._get_request_type(record)
        if request_type == "sender_mark_report":
            self._process_sender_mark_report(record)

    def _process_sender_mark_report(self, record):
        mark_id = record.request.sender_mark_report.mark_id
        mark_info = self._mark_dict.pop(mark_id)
        self._mark_id_reported = mark_id
        self._mark_reported_block = mark_info.block

    def _process_report_sender_position(self):
        # request: inquiry
        # response: report
        # sender_position_inquiry
        # sender_position_report
        pass

    def _send_mark(self, mark_type=_MarkType.DEFAULT):
        mark_id = self._mark_id
        self._mark_id += 1

        sender_mark = pb.SenderMarkRequest(mark_id=mark_id)
        request = pb.Request()
        request.sender_mark.CopyFrom(sender_mark)
        record = pb.Record()
        record.request.CopyFrom(request)
        self._forward_record(record)
        self._mark_id_sent = mark_id
        block = self._written_block_end
        self._mark_dict[mark_id] = _MarkInfo(block=block, mark_type=mark_type)
        self._mark_sent_block = block

    def _maybe_send_mark(self):
        """Send mark if we are writting the first record in a block."""
        # if self._last_block_end == self._written_block_end:
        #     return
        self._send_mark()

    def _maybe_request_read(self):
        pass
        # if we are paused
        # and more than one chunk has been written
        # and N time has elapsed
        # send message asking sender to read from last_read_offset to current_offset

    def _collect_record(self, record):
        pass

    def _behind_blocks(self) -> int:
        # behind_ids = self._mark_id_sent - self._mark_id_reported
        behind_blocks = self._mark_block_sent - self._mark_block_reported
        # print(
        #     f"BEHIND id={behind_ids} b={behind_blocks} sent={self._mark_id_sent} rep{self._mark_id_reported}"
        # )
        return behind_blocks

    def _maybe_transition_pause(self):
        """Stop sending data to the sender if it is backed up."""
        if self._behind_blocks() < self._threshold_block_high:
            return
        self._state = _SendState.PAUSED
        self._send_mark()

    def _maybe_transition_reading(self):
        """Do we have any blocks written to disk that we should start reading from."""
        pass

    def _maybe_transition_restart(self):
        """Start looking for a good opportunity to actively use sender."""
        pass
        # self._mark_position()
        # self._send_mark()

    def _maybe_transition_active(self):
        """Transition to the active state by sending collected records."""
        pass
        # if mark_position received
        #     send(collected records)

    def flush(self) -> None:
        pass

    def direct(self, record: "Record") -> None:

        self._process_record(record)
        if not self._is_control_record(record):
            self._write_record(record)

        # Transition sending state machine
        if self._state == _SendState.ACTIVE:
            self._maybe_transition_pause()
        elif self._state == _SendState.PAUSED:
            self._maybe_transition_active()
            self._maybe_transition_restart()
            self._maybe_transition_reading()
        elif self._state == _SendState.READING:
            self._maybe_transition_active()
            self._maybe_transition_restart()
        elif self._state == _SendState.RESTARTING:
            self._maybe_transition_active()

        if self._is_control_record(record):
            return

        # Execute sending state machine actions
        if self._state == _SendState.ACTIVE:
            self._forward_record(record)
            self._maybe_send_mark()
        elif self._state == _SendState.PAUSED:
            self._collect_record(record)
        elif self._state == _SendState.READING:
            self._collect_record(record)
        elif self.__state == _SendState.RESTARTING:
            self._collect_record(record)
