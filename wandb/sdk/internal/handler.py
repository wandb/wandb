"""Handle Manager."""

import json
import logging
import math
import numbers
import time
from collections import defaultdict
from queue import Queue
from threading import Event
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
    cast,
)

from wandb.proto.wandb_internal_pb2 import (
    HistoryRecord,
    InternalMessages,
    MetricRecord,
    Record,
    Result,
    RunRecord,
    SampledHistoryItem,
    SummaryItem,
    SummaryRecord,
    SummaryRecordRequest,
    SystemMetricSample,
    SystemMetricsBuffer,
)

from ..interface.interface_queue import InterfaceQueue
from ..lib import handler_util, proto_util, tracelog, wburls
from . import context, sample, tb_watcher
from .settings_static import SettingsStatic
from .system.system_monitor import SystemMonitor

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import MetricSummary


SummaryDict = Dict[str, Any]

logger = logging.getLogger(__name__)

# Update (March 5, 2024): Since ~2020/2021, when constructing the summary
# object, we had replaced the artifact path for media types with the latest
# artifact path. The primary purpose of this was to support live updating of
# media objects in the UI (since the default artifact path was fully qualified
# and would not update). However, in March of 2024, a bug was discovered with
# this approach which causes this path to be incorrect in cases where the media
# object is logged to another artifact before being logged to the run. Setting
# this to `False` disables this copy behavior. The impact is that users will
# need to refresh to see updates. Ironically, this updating behavior is not
# currently supported in the UI, so the impact of this change is minimal.
REPLACE_SUMMARY_ART_PATH_WITH_LATEST = False


def _dict_nested_set(target: Dict[str, Any], key_list: Sequence[str], v: Any) -> None:
    # recurse down the dictionary structure:

    for k in key_list[:-1]:
        target.setdefault(k, {})
        new_target = target.get(k)
        if TYPE_CHECKING:
            new_target = cast(Dict[str, Any], new_target)
        target = new_target
    # use the last element of the key to write the leaf:
    target[key_list[-1]] = v


class HandleManager:
    _consolidated_summary: SummaryDict
    _sampled_history: Dict[str, sample.UniformSampleAccumulator]
    _partial_history: Dict[str, Any]
    _run_proto: Optional[RunRecord]
    _settings: SettingsStatic
    _record_q: "Queue[Record]"
    _result_q: "Queue[Result]"
    _stopped: Event
    _writer_q: "Queue[Record]"
    _interface: InterfaceQueue
    _system_monitor: Optional[SystemMonitor]
    _tb_watcher: Optional[tb_watcher.TBWatcher]
    _metric_defines: Dict[str, MetricRecord]
    _metric_globs: Dict[str, MetricRecord]
    _metric_track: Dict[Tuple[str, ...], float]
    _metric_copy: Dict[Tuple[str, ...], Any]
    _track_time: Optional[float]
    _accumulate_time: float
    _run_start_time: Optional[float]
    _context_keeper: context.ContextKeeper

    def __init__(
        self,
        settings: SettingsStatic,
        record_q: "Queue[Record]",
        result_q: "Queue[Result]",
        stopped: Event,
        writer_q: "Queue[Record]",
        interface: InterfaceQueue,
        context_keeper: context.ContextKeeper,
    ) -> None:
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._stopped = stopped
        self._writer_q = writer_q
        self._interface = interface
        self._context_keeper = context_keeper

        self._tb_watcher = None
        self._system_monitor = None
        self._step = 0

        self._track_time = None
        self._accumulate_time = 0
        self._run_start_time = None

        # keep track of summary from key/val updates
        self._consolidated_summary = dict()
        self._sampled_history = defaultdict(sample.UniformSampleAccumulator)
        self._run_proto = None
        self._partial_history = dict()
        self._metric_defines = defaultdict(MetricRecord)
        self._metric_globs = defaultdict(MetricRecord)
        self._metric_track = dict()
        self._metric_copy = dict()
        self._internal_messages = InternalMessages()

        self._dropped_history = False

    def __len__(self) -> int:
        return self._record_q.qsize()

    def handle(self, record: Record) -> None:
        self._context_keeper.add_from_record(record)
        record_type = record.WhichOneof("record_type")
        assert record_type
        handler_str = "handle_" + record_type
        handler: Callable[[Record], None] = getattr(self, handler_str, None)  # type: ignore
        assert handler, f"unknown handle: {handler_str}"  # type: ignore
        handler(record)

    def handle_request(self, record: Record) -> None:
        request_type = record.request.WhichOneof("request_type")
        assert request_type
        handler_str = "handle_request_" + request_type
        handler: Callable[[Record], None] = getattr(self, handler_str, None)  # type: ignore
        if request_type != "network_status":
            logger.debug(f"handle_request: {request_type}")
        assert handler, f"unknown handle: {handler_str}"  # type: ignore
        handler(record)

    def _dispatch_record(self, record: Record, always_send: bool = False) -> None:
        if always_send:
            record.control.always_send = True
        tracelog.log_message_queue(record, self._writer_q)
        self._writer_q.put(record)

    def _respond_result(self, result: Result) -> None:
        tracelog.log_message_queue(result, self._result_q)
        context_id = context.context_id_from_result(result)
        self._context_keeper.release(context_id)
        self._result_q.put(result)

    def debounce(self) -> None:
        pass

    def handle_request_cancel(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_request_defer(self, record: Record) -> None:
        defer = record.request.defer
        state = defer.state

        logger.info(f"handle defer: {state}")
        # only handle flush tb (sender handles the rest)
        if state == defer.FLUSH_STATS:
            # TODO(jhr): this could block so we dont really want to call shutdown
            # from handler thread
            if self._system_monitor is not None:
                self._system_monitor.finish()
        elif state == defer.FLUSH_TB:
            if self._tb_watcher:
                # shutdown tensorboard workers so we get all metrics flushed
                self._tb_watcher.finish()
                self._tb_watcher = None
        elif state == defer.FLUSH_PARTIAL_HISTORY:
            self._flush_partial_history()
        elif state == defer.FLUSH_SUM:
            self._save_summary(self._consolidated_summary, flush=True)

        # defer is used to drive the sender finish state machine
        self._dispatch_record(record, always_send=True)

    def handle_request_login(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_request_python_packages(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_run(self, record: Record) -> None:
        if self._settings._offline:
            self._run_proto = record.run
            result = proto_util._result_from_record(record)
            result.run_result.run.CopyFrom(record.run)
            self._respond_result(result)
        self._dispatch_record(record)

    def handle_stats(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_config(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_output(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_output_raw(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_files(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_request_link_artifact(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_use_artifact(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_artifact(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_alert(self, record: Record) -> None:
        self._dispatch_record(record)

    def _save_summary(self, summary_dict: SummaryDict, flush: bool = False) -> None:
        summary = SummaryRecord()
        for k, v in summary_dict.items():
            update = summary.update.add()
            update.key = k
            update.value_json = json.dumps(v)
        if flush:
            record = Record(summary=summary)
            self._dispatch_record(record)
        elif not self._settings._offline:
            # Send this summary update as a request since we aren't persisting every update
            summary_record = SummaryRecordRequest(summary=summary)
            request_record = self._interface._make_request(
                summary_record=summary_record
            )
            self._dispatch_record(request_record)

    def _save_history(
        self,
        history: HistoryRecord,
    ) -> None:
        for item in history.item:
            # TODO(jhr) save nested keys?
            k = item.key
            v = json.loads(item.value_json)
            if isinstance(v, numbers.Real):
                self._sampled_history[k].add(v)

    def _update_summary_metrics(
        self,
        s: "MetricSummary",
        kl: List[str],
        v: "numbers.Real",
        float_v: float,
        goal_max: Optional[bool],
    ) -> bool:
        updated = False
        best_key: Optional[Tuple[str, ...]] = None
        if s.none:
            return False
        if s.copy:
            # non-key list copy already done in _update_summary
            if len(kl) > 1:
                _dict_nested_set(self._consolidated_summary, kl, v)
                return True
        if s.last:
            last_key = tuple(kl + ["last"])
            old_last = self._metric_track.get(last_key)
            if old_last is None or float_v != old_last:
                self._metric_track[last_key] = float_v
                _dict_nested_set(self._consolidated_summary, last_key, v)
                updated = True
        if s.best:
            best_key = tuple(kl + ["best"])
        if s.max or best_key and goal_max:
            max_key = tuple(kl + ["max"])
            old_max = self._metric_track.get(max_key)
            if old_max is None or float_v > old_max:
                self._metric_track[max_key] = float_v
                if s.max:
                    _dict_nested_set(self._consolidated_summary, max_key, v)
                    updated = True
                if best_key:
                    _dict_nested_set(self._consolidated_summary, best_key, v)
                    updated = True
        # defaulting to minimize if goal is not specified
        if s.min or best_key and not goal_max:
            min_key = tuple(kl + ["min"])
            old_min = self._metric_track.get(min_key)
            if old_min is None or float_v < old_min:
                self._metric_track[min_key] = float_v
                if s.min:
                    _dict_nested_set(self._consolidated_summary, min_key, v)
                    updated = True
                if best_key:
                    _dict_nested_set(self._consolidated_summary, best_key, v)
                    updated = True
        if s.mean:
            tot_key = tuple(kl + ["tot"])
            num_key = tuple(kl + ["num"])
            avg_key = tuple(kl + ["mean"])
            tot = self._metric_track.get(tot_key, 0.0)
            num = self._metric_track.get(num_key, 0)
            tot += float_v
            num += 1
            self._metric_track[tot_key] = tot
            self._metric_track[num_key] = num
            _dict_nested_set(self._consolidated_summary, avg_key, tot / num)
            updated = True
        return updated

    def _update_summary_leaf(
        self,
        kl: List[str],
        v: Any,
        d: Optional[MetricRecord] = None,
    ) -> bool:
        has_summary = d and d.HasField("summary")
        if len(kl) == 1:
            copy_key = tuple(kl)
            old_copy = self._metric_copy.get(copy_key)
            if old_copy is None or v != old_copy:
                self._metric_copy[copy_key] = v
                # Store copy metric if not specified, or copy behavior
                if not has_summary or (d and d.summary.copy):
                    self._consolidated_summary[kl[0]] = v
                    return True
        if not d:
            return False
        if not has_summary:
            return False
        if not isinstance(v, numbers.Real):
            return False
        if math.isnan(v):
            return False
        float_v = float(v)
        goal_max = None
        if d.goal:
            goal_max = d.goal == d.GOAL_MAXIMIZE
        if self._update_summary_metrics(
            d.summary, kl=kl, v=v, float_v=float_v, goal_max=goal_max
        ):
            return True
        return False

    def _update_summary_list(
        self,
        kl: List[str],
        v: Any,
        d: Optional[MetricRecord] = None,
    ) -> bool:
        metric_key = ".".join([k.replace(".", "\\.") for k in kl])
        d = self._metric_defines.get(metric_key, d)
        # if the dict has _type key, it's a wandb table object
        if isinstance(v, dict) and not handler_util.metric_is_wandb_dict(v):
            updated = False
            for nk, nv in v.items():
                if self._update_summary_list(kl=kl[:] + [nk], v=nv, d=d):
                    updated = True
            return updated
        # If the dict is a media object, update the pointer to the latest alias
        elif (
            REPLACE_SUMMARY_ART_PATH_WITH_LATEST
            and isinstance(v, dict)
            and handler_util.metric_is_wandb_dict(v)
        ):
            if "_latest_artifact_path" in v and "artifact_path" in v:
                # TODO: Make non-destructive?
                v["artifact_path"] = v["_latest_artifact_path"]
        updated = self._update_summary_leaf(kl=kl, v=v, d=d)
        return updated

    def _update_summary_media_objects(self, v: Dict[str, Any]) -> Dict[str, Any]:
        # For now, non-recursive - just top level
        for nk, nv in v.items():
            if REPLACE_SUMMARY_ART_PATH_WITH_LATEST and (
                isinstance(nv, dict)
                and handler_util.metric_is_wandb_dict(nv)
                and "_latest_artifact_path" in nv
                and "artifact_path" in nv
            ):
                # TODO: Make non-destructive?
                nv["artifact_path"] = nv["_latest_artifact_path"]
                v[nk] = nv
        return v

    def _update_summary(self, history_dict: Dict[str, Any]) -> List[str]:
        # keep old behavior fast path if no define metrics have been used
        if not self._metric_defines:
            history_dict = self._update_summary_media_objects(history_dict)
            self._consolidated_summary.update(history_dict)
            return list(history_dict.keys())
        updated_keys = []
        for k, v in history_dict.items():
            if self._update_summary_list(kl=[k], v=v):
                updated_keys.append(k)
        return updated_keys

    def _history_assign_step(
        self,
        history: HistoryRecord,
        history_dict: Dict[str, Any],
    ) -> None:
        has_step = history.HasField("step")
        item = history.item.add()
        item.key = "_step"
        if has_step:
            step = history.step.num
            history_dict["_step"] = step
            item.value_json = json.dumps(step)
            self._step = step + 1
        else:
            history_dict["_step"] = self._step
            item.value_json = json.dumps(self._step)
            self._step += 1

    def _history_define_metric(self, hkey: str) -> Optional[MetricRecord]:
        """Check for hkey match in glob metrics and return the defined metric."""
        # Dont define metric for internal metrics
        if hkey.startswith("_"):
            return None
        for k, mglob in self._metric_globs.items():
            if k.endswith("*"):
                if hkey.startswith(k[:-1]):
                    m = MetricRecord()
                    m.CopyFrom(mglob)
                    m.ClearField("glob_name")
                    m.options.defined = False
                    m.name = hkey
                    return m
        return None

    def _history_update_leaf(
        self,
        kl: List[str],
        v: Any,
        history_dict: Dict[str, Any],
        update_history: Dict[str, Any],
    ) -> None:
        hkey = ".".join([k.replace(".", "\\.") for k in kl])
        m = self._metric_defines.get(hkey)
        if not m:
            m = self._history_define_metric(hkey)
            if not m:
                return
            mr = Record()
            mr.metric.CopyFrom(m)
            mr.control.local = True  # Dont store this, just send it
            self._handle_defined_metric(mr)

        if m.options.step_sync and m.step_metric:
            if m.step_metric not in history_dict:
                copy_key = tuple([m.step_metric])
                step = self._metric_copy.get(copy_key)
                if step is not None:
                    update_history[m.step_metric] = step

    def _history_update_list(
        self,
        kl: List[str],
        v: Any,
        history_dict: Dict[str, Any],
        update_history: Dict[str, Any],
    ) -> None:
        if isinstance(v, dict):
            for nk, nv in v.items():
                self._history_update_list(
                    kl=kl[:] + [nk],
                    v=nv,
                    history_dict=history_dict,
                    update_history=update_history,
                )
            return
        self._history_update_leaf(
            kl=kl, v=v, history_dict=history_dict, update_history=update_history
        )

    def _history_update(
        self,
        history: HistoryRecord,
        history_dict: Dict[str, Any],
    ) -> None:
        #  if syncing an old run, we can skip this logic
        if history_dict.get("_step") is None:
            self._history_assign_step(history, history_dict)

        update_history: Dict[str, Any] = {}
        # Look for metric matches
        if self._metric_defines or self._metric_globs:
            for hkey, hval in history_dict.items():
                self._history_update_list([hkey], hval, history_dict, update_history)

        if update_history:
            history_dict.update(update_history)
            for k, v in update_history.items():
                item = history.item.add()
                item.key = k
                item.value_json = json.dumps(v)

    def handle_history(self, record: Record) -> None:
        history_dict = proto_util.dict_from_proto_list(record.history.item)

        # Inject _runtime if it is not present
        if history_dict is not None:
            if "_runtime" not in history_dict:
                self._history_assign_runtime(record.history, history_dict)

        self._history_update(record.history, history_dict)
        self._dispatch_record(record)
        self._save_history(record.history)
        # update summary from history
        updated_keys = self._update_summary(history_dict)
        if updated_keys:
            updated_items = {k: self._consolidated_summary[k] for k in updated_keys}
            self._save_summary(updated_items)

    def _flush_partial_history(
        self,
        step: Optional[int] = None,
    ) -> None:
        if not self._partial_history:
            return

        history = HistoryRecord()
        for k, v in self._partial_history.items():
            item = history.item.add()
            item.key = k
            item.value_json = json.dumps(v)
        if step is not None:
            history.step.num = step
        self.handle_history(Record(history=history))
        self._partial_history = {}

    def handle_request_sender_mark_report(self, record: Record) -> None:
        self._dispatch_record(record, always_send=True)

    def handle_request_status_report(self, record: Record) -> None:
        self._dispatch_record(record, always_send=True)

    def handle_request_partial_history(self, record: Record) -> None:
        partial_history = record.request.partial_history

        flush = None
        if partial_history.HasField("action"):
            flush = partial_history.action.flush

        step = None
        if partial_history.HasField("step"):
            step = partial_history.step.num

        history_dict = proto_util.dict_from_proto_list(partial_history.item)
        if step is not None:
            if step < self._step:
                if not self._dropped_history:
                    message = (
                        "Step only supports monotonically increasing values, use define_metric to set a custom x "
                        f"axis. For details see: {wburls.wburls.get('wandb_define_metric')}"
                    )
                    self._internal_messages.warning.append(message)
                    self._dropped_history = True
                message = (
                    f"(User provided step: {step} is less than current step: {self._step}. "
                    f"Dropping entry: {history_dict})."
                )
                self._internal_messages.warning.append(message)
                return
            elif step > self._step:
                self._flush_partial_history()
                self._step = step
        elif flush is None:
            flush = True

        self._partial_history.update(history_dict)

        if flush:
            self._flush_partial_history(self._step)

    def handle_summary(self, record: Record) -> None:
        summary = record.summary
        for item in summary.update:
            if len(item.nested_key) > 0:
                # we use either key or nested_key -- not both
                assert item.key == ""
                key = tuple(item.nested_key)
            else:
                # no counter-assertion here, because technically
                # summary[""] is valid
                key = (item.key,)

            target = self._consolidated_summary

            # recurse down the dictionary structure:
            for prop in key[:-1]:
                target = target[prop]

            # use the last element of the key to write the leaf:
            target[key[-1]] = json.loads(item.value_json)

        for item in summary.remove:
            if len(item.nested_key) > 0:
                # we use either key or nested_key -- not both
                assert item.key == ""
                key = tuple(item.nested_key)
            else:
                # no counter-assertion here, because technically
                # summary[""] is valid
                key = (item.key,)

            target = self._consolidated_summary

            # recurse down the dictionary structure:
            for prop in key[:-1]:
                target = target[prop]

            # use the last element of the key to erase the leaf:
            del target[key[-1]]

        self._save_summary(self._consolidated_summary)

    def handle_exit(self, record: Record) -> None:
        if self._track_time is not None:
            self._accumulate_time += time.time() - self._track_time
        record.exit.runtime = int(self._accumulate_time)
        self._dispatch_record(record, always_send=True)

    def handle_final(self, record: Record) -> None:
        self._dispatch_record(record, always_send=True)

    def handle_preempting(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_header(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_footer(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_request_check_version(self, record: Record) -> None:
        if self._settings._offline:
            result = proto_util._result_from_record(record)
            self._respond_result(result)
        else:
            self._dispatch_record(record)

    def handle_request_attach(self, record: Record) -> None:
        result = proto_util._result_from_record(record)
        attach_id = record.request.attach.attach_id
        assert attach_id
        assert self._run_proto
        result.response.attach_response.run.CopyFrom(self._run_proto)
        self._respond_result(result)

    def handle_request_log_artifact(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_telemetry(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_request_run_start(self, record: Record) -> None:
        run_start = record.request.run_start
        assert run_start
        assert run_start.run

        self._run_proto = run_start.run

        self._run_start_time = run_start.run.start_time.ToMicroseconds() / 1e6

        self._track_time = time.time()
        if run_start.run.resumed and run_start.run.runtime:
            self._accumulate_time = run_start.run.runtime
        else:
            self._accumulate_time = 0

        # system monitor
        self._system_monitor = SystemMonitor(
            self._settings,
            self._interface,
        )
        if not self._settings._disable_stats:
            self._system_monitor.start()
        if not self._settings._disable_meta and not run_start.run.resumed:
            self._system_monitor.probe(publish=True)

        self._tb_watcher = tb_watcher.TBWatcher(
            self._settings, interface=self._interface, run_proto=run_start.run
        )

        if run_start.run.resumed or run_start.run.forked:
            self._step = run_start.run.starting_step
        result = proto_util._result_from_record(record)
        self._respond_result(result)

    def handle_request_resume(self, record: Record) -> None:
        if self._system_monitor is not None:
            logger.info("starting system metrics thread")
            self._system_monitor.start()

        if self._track_time is not None:
            self._accumulate_time += time.time() - self._track_time
        self._track_time = time.time()

    def handle_request_pause(self, record: Record) -> None:
        if self._system_monitor is not None:
            logger.info("stopping system metrics thread")
            self._system_monitor.finish()
        if self._track_time is not None:
            self._accumulate_time += time.time() - self._track_time
            self._track_time = None

    def handle_request_poll_exit(self, record: Record) -> None:
        self._dispatch_record(record, always_send=True)

    def handle_request_stop_status(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_request_network_status(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_request_internal_messages(self, record: Record) -> None:
        result = proto_util._result_from_record(record)
        result.response.internal_messages_response.messages.CopyFrom(
            self._internal_messages
        )
        self._internal_messages.Clear()
        self._respond_result(result)

    def handle_request_status(self, record: Record) -> None:
        result = proto_util._result_from_record(record)
        self._respond_result(result)

    def handle_request_get_summary(self, record: Record) -> None:
        result = proto_util._result_from_record(record)
        for key, value in self._consolidated_summary.items():
            item = SummaryItem()
            item.key = key
            item.value_json = json.dumps(value)
            result.response.get_summary_response.item.append(item)
        self._respond_result(result)

    def handle_request_get_system_metrics(self, record: Record) -> None:
        result = proto_util._result_from_record(record)
        if self._system_monitor is None:
            return

        buffer = self._system_monitor.buffer
        for key, samples in buffer.items():
            buff = []
            for s in samples:
                sms = SystemMetricSample()
                sms.timestamp.FromMicroseconds(int(s[0] * 1e6))
                sms.value = s[1]
                buff.append(sms)

            result.response.get_system_metrics_response.system_metrics[key].CopyFrom(
                SystemMetricsBuffer(record=buff)
            )

        self._respond_result(result)

    def handle_tbrecord(self, record: Record) -> None:
        logger.info("handling tbrecord: %s", record)
        if self._tb_watcher:
            tbrecord = record.tbrecord
            self._tb_watcher.add(tbrecord.log_dir, tbrecord.save, tbrecord.root_dir)
        self._dispatch_record(record)

    def _handle_defined_metric(self, record: Record) -> None:
        metric = record.metric
        if metric._control.overwrite:
            self._metric_defines[metric.name].CopyFrom(metric)
        else:
            self._metric_defines[metric.name].MergeFrom(metric)

        # before dispatching, make sure step_metric is defined, if not define it and
        # dispatch it locally first
        metric = self._metric_defines[metric.name]
        if metric.step_metric and metric.step_metric not in self._metric_defines:
            m = MetricRecord(name=metric.step_metric)
            self._metric_defines[metric.step_metric] = m
            mr = Record()
            mr.metric.CopyFrom(m)
            mr.control.local = True  # Don't store this, just send it
            self._dispatch_record(mr)

        self._dispatch_record(record)

    def _handle_glob_metric(self, record: Record) -> None:
        metric = record.metric
        if metric._control.overwrite:
            self._metric_globs[metric.glob_name].CopyFrom(metric)
        else:
            self._metric_globs[metric.glob_name].MergeFrom(metric)
        self._dispatch_record(record)

    def handle_metric(self, record: Record) -> None:
        """Handle MetricRecord.

        Walkthrough of the life of a MetricRecord:

        Metric defined:
        - run.define_metric() parses arguments create wandb_metric.Metric
        - build MetricRecord publish to interface
        - handler (this function) keeps list of metrics published:
          - self._metric_defines: Fully defined metrics
          - self._metric_globs: metrics that have a wildcard
        - dispatch writer and sender thread
          - writer: records are saved to persistent store
          - sender: fully defined metrics get mapped into metadata for UI

        History logged:
        - handle_history
        - check if metric matches _metric_defines
        - if not, check if metric matches _metric_globs
        - if _metric globs match, generate defined metric and call _handle_metric

        Args:
            record (Record): Metric record to process
        """
        if record.metric.name:
            self._handle_defined_metric(record)
        elif record.metric.glob_name:
            self._handle_glob_metric(record)

    def handle_request_sampled_history(self, record: Record) -> None:
        result = proto_util._result_from_record(record)
        for key, sampled in self._sampled_history.items():
            item = SampledHistoryItem()
            item.key = key
            values: Iterable[Any] = sampled.get()
            if all(isinstance(i, numbers.Integral) for i in values):
                try:
                    item.values_int.extend(values)
                except ValueError:
                    # it is safe to ignore these as this is for display information
                    pass
            elif all(isinstance(i, numbers.Real) for i in values):
                item.values_float.extend(values)
            result.response.sampled_history_response.item.append(item)
        self._respond_result(result)

    def handle_request_server_info(self, record: Record) -> None:
        self._dispatch_record(record, always_send=True)

    def handle_request_keepalive(self, record: Record) -> None:
        """Handle a keepalive request.

        Keepalive is a noop, we just want to verify transport is alive.
        """

    def handle_request_run_status(self, record: Record) -> None:
        self._dispatch_record(record, always_send=True)

    def handle_request_shutdown(self, record: Record) -> None:
        # TODO(jhr): should we drain things and stop new requests from coming in?
        result = proto_util._result_from_record(record)
        self._respond_result(result)
        self._stopped.set()

    def finish(self) -> None:
        logger.info("shutting down handler")
        if self._system_monitor is not None:
            self._system_monitor.finish()
        if self._tb_watcher:
            self._tb_watcher.finish()
        # self._context_keeper._debug_print_orphans()

    def __next__(self) -> Record:
        return self._record_q.get(block=True)

    next = __next__

    def _history_assign_runtime(
        self,
        history: HistoryRecord,
        history_dict: Dict[str, Any],
    ) -> None:
        # _runtime calculation is meaningless if there is no _timestamp
        if "_timestamp" not in history_dict:
            return
        # if it is offline sync, self._run_start_time is None
        # in that case set it to the first tfevent timestamp
        if self._run_start_time is None:
            self._run_start_time = history_dict["_timestamp"]
        history_dict["_runtime"] = history_dict["_timestamp"] - self._run_start_time
        item = history.item.add()
        item.key = "_runtime"
        item.value_json = json.dumps(history_dict[item.key])
