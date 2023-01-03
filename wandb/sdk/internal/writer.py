"""Writer thread."""

import logging
from typing import TYPE_CHECKING, Callable, Optional, Set

from wandb.proto import wandb_internal_pb2 as pb

from ..lib import proto_util, tracelog
from . import context, datastore, flow_control
from .settings_static import SettingsStatic

if TYPE_CHECKING:
    from queue import Queue


logger = logging.getLogger(__name__)


class WriteManager:
    _settings: SettingsStatic
    _record_q: "Queue[pb.Record]"
    _result_q: "Queue[pb.Result]"
    _sender_q: "Queue[pb.Record]"
    _ds: Optional[datastore.DataStore]
    _flow_control: Optional[flow_control.FlowControl]
    _status_report: Optional["pb.StatusReportRequest"]
    _context_keeper: context.ContextKeeper
    _sender_cancel_set: Set[str]
    _record_num: int

    def __init__(
        self,
        settings: SettingsStatic,
        record_q: "Queue[pb.Record]",
        result_q: "Queue[pb.Result]",
        sender_q: "Queue[pb.Record]",
        context_keeper: context.ContextKeeper,
    ):
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._sender_q = sender_q
        self._context_keeper = context_keeper
        self._sender_cancel_set = set()
        self._ds = None
        self._flow_control = None
        self._flow_debug = False
        self._flow_debug = True
        self._status_report = None
        self._record_num = 0

    def open(self) -> None:
        self._ds = datastore.DataStore()
        self._ds.open_for_write(self._settings.sync_file)
        # TODO(mempressure): for debug use only, remove this eventually
        debug_kwargs = dict(
            _threshold_bytes_high=1000,
            _threshold_bytes_mid=500,
            _threshold_bytes_low=200,
            _mark_granularity_bytes=100,
            _recovering_bytes_min=300,
        )
        kwargs = debug_kwargs if self._flow_debug else {}
        self._flow_control = flow_control.FlowControl(
            settings=self._settings,
            write_record=self._write_record,
            forward_record=self._forward_record,
            recover_records=self._recover_records,
            **kwargs,
        )

    def _forward_record(self, record: "pb.Record") -> None:
        self._context_keeper.add_from_record(record)
        tracelog.log_message_queue(record, self._sender_q)
        self._sender_q.put(record)

    def _write_record(self, record: "pb.Record") -> int:
        assert self._ds

        self._record_num += 1
        proto_util._assign_record_num(record, self._record_num)
        # print("WRITE REC", record.num, record)
        ret = self._ds.write(record)
        assert ret is not None

        (_start_offset, end_offset, flush_offset) = ret
        proto_util._assign_end_offset(record, end_offset)
        return end_offset

    def _ensure_flushed(self, offset: int) -> None:
        if self._ds:
            self._ds.ensure_flushed(offset)

    def _recover_records(self, start: int, end: int) -> None:
        record = pb.Record()
        request = pb.Request()
        sender_read = pb.SenderReadRequest(start_offset=start, final_offset=end)
        for cancel_id in self._sender_cancel_set:
            sender_read.cancel_list.append(cancel_id)
        request.sender_read.CopyFrom(sender_read)
        record.request.CopyFrom(request)
        self._ensure_flushed(end)
        self._forward_record(record)

    def _write(self, record: "pb.Record") -> None:
        if not self._ds:
            self.open()
        assert self._flow_control

        use_flow_control = self._settings._flow_control and not self._settings._offline
        if use_flow_control:
            self._flow_control.flow(record)
        else:
            if not record.control.local:
                self._write_record(record)
            if not self._settings._offline or record.control.always_send:
                self._forward_record(record)

    def write(self, record: "pb.Record") -> None:
        record_type = record.WhichOneof("record_type")
        assert record_type
        writer_str = "write_" + record_type
        write_handler: Callable[["pb.Record"], None] = getattr(
            self, writer_str, self._write
        )
        write_handler(record)

    def write_request(self, record: "pb.Record") -> None:
        request_type = record.request.WhichOneof("request_type")
        assert request_type
        write_request_str = "write_request_" + request_type
        write_request_handler: Optional[Callable[["pb.Record"], None]] = getattr(
            self, write_request_str, None
        )
        if write_request_handler:
            return write_request_handler(record)
        self._write(record)

    def write_request_run_status(self, record: "pb.Record") -> None:
        result = proto_util._result_from_record(record)
        if self._status_report:
            result.response.run_status_response.sync_time.CopyFrom(
                self._status_report.sync_time
            )
            send_record_num = self._status_report.record_num
            result.response.run_status_response.sync_items_total = self._record_num
            result.response.run_status_response.sync_items_pending = (
                self._record_num - send_record_num
            )
        # TODO(mempressure): add logic to populate run_status_response
        self._respond_result(result)

    def write_request_status_report(self, record: "pb.Record") -> None:
        self._status_report = record.request.status_report
        self._write(record)

    def write_request_cancel(self, record: "pb.Record") -> None:
        cancel_id = record.request.cancel.cancel_slot
        cancelled = self._context_keeper.cancel(cancel_id)
        if not cancelled:
            self._sender_cancel_set.add(cancel_id)

    def _respond_result(self, result: "pb.Result") -> None:
        tracelog.log_message_queue(result, self._result_q)
        self._result_q.put(result)

    def finish(self) -> None:
        if self._ds:
            self._ds.close()
        if self._flow_control:
            self._flow_control.flush()
        self._context_keeper._debug_print_orphans(print_to_stdout=self._settings._debug)

    def debounce(self) -> None:
        pass
