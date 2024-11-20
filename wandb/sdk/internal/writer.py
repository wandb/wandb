"""Writer thread."""

import logging
from typing import TYPE_CHECKING, Callable, Optional

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb

from ..interface.interface_queue import InterfaceQueue
from ..lib import proto_util, telemetry
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
    _interface: InterfaceQueue
    _context_keeper: context.ContextKeeper

    _ds: Optional[datastore.DataStore]
    _flow_control: Optional[flow_control.FlowControl]
    _status_report: Optional["pb.StatusReportRequest"]
    _record_num: int
    _telemetry_obj: tpb.TelemetryRecord
    _telemetry_overflow: bool
    _use_flow_control: bool

    # TODO(cancel_paused): implement me
    # _sender_cancel_set: Set[str]

    def __init__(
        self,
        settings: SettingsStatic,
        record_q: "Queue[pb.Record]",
        result_q: "Queue[pb.Result]",
        sender_q: "Queue[pb.Record]",
        interface: InterfaceQueue,
        context_keeper: context.ContextKeeper,
    ):
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._sender_q = sender_q
        self._interface = interface
        self._context_keeper = context_keeper

        # TODO(cancel_paused): implement me
        # self._sender_cancel_set = set()

        self._ds = None
        self._flow_control = None
        self._status_report = None
        self._record_num = 0
        self._telemetry_obj = tpb.TelemetryRecord()
        self._telemetry_overflow = False
        self._use_flow_control = not (
            self._settings.x_flow_control_disabled or self._settings._offline
        )

    def open(self) -> None:
        self._ds = datastore.DataStore()
        self._ds.open_for_write(self._settings.sync_file)
        self._flow_control = flow_control.FlowControl(
            settings=self._settings,
            write_record=self._write_record,
            forward_record=self._forward_record,
            pause_marker=self._pause_marker,
            recover_records=self._recover_records,
        )

    def _forward_record(self, record: "pb.Record") -> None:
        self._context_keeper.add_from_record(record)
        self._sender_q.put(record)

    def _send_mark(self) -> None:
        sender_mark = pb.SenderMarkRequest()
        record = self._interface._make_request(sender_mark=sender_mark)
        self._forward_record(record)

    def _maybe_send_telemetry(self) -> None:
        if self._telemetry_overflow:
            return
        self._telemetry_overflow = True
        with telemetry.context(obj=self._telemetry_obj) as tel:
            tel.feature.flow_control_overflow = True
        telemetry_record = pb.TelemetryRecordRequest(telemetry=self._telemetry_obj)
        record = self._interface._make_request(telemetry_record=telemetry_record)
        self._forward_record(record)

    def _pause_marker(self) -> None:
        self._maybe_send_telemetry()
        self._send_mark()

    def _write_record(self, record: "pb.Record") -> int:
        assert self._ds

        self._record_num += 1
        proto_util._assign_record_num(record, self._record_num)
        ret = self._ds.write(record)
        assert ret is not None

        _start_offset, end_offset, _flush_offset = ret
        proto_util._assign_end_offset(record, end_offset)
        return end_offset

    def _ensure_flushed(self, offset: int) -> None:
        if self._ds:
            self._ds.ensure_flushed(offset)

    def _recover_records(self, start: int, end: int) -> None:
        sender_read = pb.SenderReadRequest(start_offset=start, final_offset=end)
        # TODO(cancel_paused): implement me
        # for cancel_id in self._sender_cancel_set:
        #     sender_read.cancel_list.append(cancel_id)
        record = self._interface._make_request(sender_read=sender_read)
        self._ensure_flushed(end)
        self._forward_record(record)

    def _write(self, record: "pb.Record") -> None:
        if not self._ds:
            self.open()
        assert self._flow_control

        if not record.control.local:
            self._write_record(record)

        if self._use_flow_control:
            self._flow_control.flow(record)
        elif not self._settings._offline or record.control.always_send:
            # when flow_control is disabled we pass through all records to
            # the sender as long as we are online.  The exception is there
            # are special records that we always pass to the sender
            # (namely the exit record so we can trigger the defer shutdown
            # state machine)
            self._forward_record(record)

    def write(self, record: "pb.Record") -> None:
        record_type = record.WhichOneof("record_type")
        assert record_type
        writer_str = "write_" + record_type
        write_handler: Callable[[pb.Record], None] = getattr(
            self, writer_str, self._write
        )
        write_handler(record)

    def write_request(self, record: "pb.Record") -> None:
        request_type = record.request.WhichOneof("request_type")
        assert request_type
        write_request_str = "write_request_" + request_type
        write_request_handler: Optional[Callable[[pb.Record], None]] = getattr(
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
        self._respond_result(result)

    def write_request_status_report(self, record: "pb.Record") -> None:
        self._status_report = record.request.status_report
        self._write(record)

    def write_request_cancel(self, record: "pb.Record") -> None:
        cancel_id = record.request.cancel.cancel_slot
        self._context_keeper.cancel(cancel_id)

        # TODO(cancel_paused): implement me
        # cancelled = self._context_keeper.cancel(cancel_id)
        # if not cancelled:
        #     self._sender_cancel_set.add(cancel_id)

    def _respond_result(self, result: "pb.Result") -> None:
        self._result_q.put(result)

    def finish(self) -> None:
        if self._flow_control:
            self._flow_control.flush()
        if self._ds:
            self._ds.close()
        # TODO(debug_context) see context.py
        # self._context_keeper._debug_print_orphans(print_to_stdout=self._settings._debug)

    def debounce(self) -> None:
        pass
