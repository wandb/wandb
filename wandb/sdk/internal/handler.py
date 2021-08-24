#
# -*- coding: utf-8 -*-
"""Handle Manager."""

from __future__ import print_function

import json
import logging
import math
import numbers
import os
from threading import Event
import time
from typing import (
    Any,
    Callable,
    cast,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
    TYPE_CHECKING,
)

import six
from six.moves.queue import Queue
from wandb.proto import wandb_internal_pb2
from wandb.proto.wandb_internal_pb2 import Record, Result

from . import meta, sample, stats
from . import tb_watcher
from .settings_static import SettingsStatic
from ..interface.interface import BackendSender
from ..lib import handler_util, proto_util

SummaryDict = Dict[str, Any]

logger = logging.getLogger(__name__)


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


class HandleManager(object):
    _consolidated_summary: SummaryDict
    _sampled_history: Dict[str, sample.UniformSampleAccumulator]
    _settings: SettingsStatic
    _record_q: "Queue[Record]"
    _result_q: "Queue[Result]"
    _stopped: Event
    _sender_q: "Queue[Record]"
    _writer_q: "Queue[Record]"
    _interface: BackendSender
    _system_stats: Optional[stats.SystemStats]
    _tb_watcher: Optional[tb_watcher.TBWatcher]
    _metric_defines: Dict[str, wandb_internal_pb2.MetricRecord]
    _metric_globs: Dict[str, wandb_internal_pb2.MetricRecord]
    _metric_track: Dict[Tuple[str, ...], float]
    _metric_copy: Dict[Tuple[str, ...], Any]
    _track_time: Optional[float]
    _accumulate_time: float

    def __init__(
        self,
        settings: SettingsStatic,
        record_q: "Queue[Record]",
        result_q: "Queue[Result]",
        stopped: Event,
        sender_q: "Queue[Record]",
        writer_q: "Queue[Record]",
        interface: BackendSender,
    ) -> None:
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._stopped = stopped
        self._sender_q = sender_q
        self._writer_q = writer_q
        self._interface = interface

        self._tb_watcher = None
        self._system_stats = None
        self._step = 0

        self._track_time = None
        self._accumulate_time = 0
        self._run_start_time = 0

        # keep track of summary from key/val updates
        self._consolidated_summary = dict()
        self._sampled_history = dict()
        self._metric_defines = dict()
        self._metric_globs = dict()
        self._metric_track = dict()
        self._metric_copy = dict()

    def __len__(self) -> int:
        return self._record_q.qsize()

    def handle(self, record: Record) -> None:
        record_type = record.WhichOneof("record_type")
        assert record_type
        handler_str = "handle_" + record_type
        handler: Callable[[Record], None] = getattr(self, handler_str, None)
        assert handler, "unknown handle: {}".format(handler_str)
        handler(record)

    def handle_request(self, record: Record) -> None:
        request_type = record.request.WhichOneof("request_type")
        assert request_type
        handler_str = "handle_request_" + request_type
        handler: Callable[[Record], None] = getattr(self, handler_str, None)
        if request_type != "network_status":
            logger.debug("handle_request: {}".format(request_type))
        assert handler, "unknown handle: {}".format(handler_str)
        handler(record)

    def _dispatch_record(self, record: Record, always_send: bool = False) -> None:
        if not self._settings._offline or always_send:
            self._sender_q.put(record)
        if not record.control.local and self._writer_q:
            self._writer_q.put(record)

    def debounce(self) -> None:
        pass

    def handle_request_defer(self, record: Record) -> None:
        defer = record.request.defer
        state = defer.state

        logger.info("handle defer: {}".format(state))
        # only handle flush tb (sender handles the rest)
        if state == defer.FLUSH_STATS:
            if self._system_stats:
                # TODO(jhr): this could block so we dont really want to call shutdown
                # from handler thread
                self._system_stats.shutdown()
        elif state == defer.FLUSH_TB:
            if self._tb_watcher:
                # shutdown tensorboard workers so we get all metrics flushed
                self._tb_watcher.finish()
                self._tb_watcher = None
        elif state == defer.FLUSH_SUM:
            self._save_summary(self._consolidated_summary, flush=True)

        # defer is used to drive the sender finish state machine
        self._dispatch_record(record, always_send=True)

    def handle_request_login(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_run(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_stats(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_config(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_output(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_files(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_artifact(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_alert(self, record: Record) -> None:
        self._dispatch_record(record)

    def _save_summary(self, summary_dict: SummaryDict, flush: bool = False) -> None:
        summary = wandb_internal_pb2.SummaryRecord()
        for k, v in six.iteritems(summary_dict):
            update = summary.update.add()
            update.key = k
            update.value_json = json.dumps(v)
        record = wandb_internal_pb2.Record(summary=summary)
        if flush:
            self._dispatch_record(record)
        elif not self._settings._offline:
            self._sender_q.put(record)

    def _save_history(self, record: Record) -> None:
        for item in record.history.item:
            # TODO(jhr) save nested keys?
            k = item.key
            v = json.loads(item.value_json)
            if isinstance(v, numbers.Real):
                self._sampled_history.setdefault(k, sample.UniformSampleAccumulator())
                self._sampled_history[k].add(v)

    def _update_summary_metrics(
        self,
        s: wandb_internal_pb2.MetricSummary,
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
            # non key list copy already done in _update_summary
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
        # defaulting to minimize if goal is not supecified
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
        d: Optional[wandb_internal_pb2.MetricRecord] = None,
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
        d: Optional[wandb_internal_pb2.MetricRecord] = None,
    ) -> bool:
        metric_key = ".".join([k.replace(".", "\\.") for k in kl])
        d = self._metric_defines.get(metric_key, d)
        # if the dict has _type key, its a wandb table object
        if isinstance(v, dict) and not handler_util.metric_is_wandb_dict(v):
            updated = False
            for nk, nv in six.iteritems(v):
                if self._update_summary_list(kl=kl[:] + [nk], v=nv, d=d):
                    updated = True
            return updated
        # If the dict is a media object, update the pointer to the latest alias
        elif isinstance(v, dict) and handler_util.metric_is_wandb_dict(v):
            if "_latest_artifact_path" in v and "artifact_path" in v:
                # TODO: Make non-destructive?
                v["artifact_path"] = v["_latest_artifact_path"]
        updated = self._update_summary_leaf(kl=kl, v=v, d=d)
        return updated

    def _update_summary_media_objects(self, v: Dict[str, Any]) -> Dict[str, Any]:
        # For now, non recursive - just top level
        for nk, nv in six.iteritems(v):
            if (
                isinstance(nv, dict)
                and handler_util.metric_is_wandb_dict(nv)
                and "_latest_artifact_path" in nv
                and "artifact_path" in nv
            ):
                # TODO: Make non-destructive?
                nv["artifact_path"] = nv["_latest_artifact_path"]
                v[nk] = nv
        return v

    def _update_summary(self, history_dict: Dict[str, Any]) -> bool:
        # keep old behavior fast path if no define metrics have been used
        if not self._metric_defines:
            history_dict = self._update_summary_media_objects(history_dict)
            self._consolidated_summary.update(history_dict)
            return True
        updated = False
        for k, v in six.iteritems(history_dict):
            if self._update_summary_list(kl=[k], v=v):
                updated = True
        return updated

    def _history_assign_step(self, record: Record, history_dict: Dict) -> None:
        has_step = record.history.HasField("step")
        item = record.history.item.add()
        item.key = "_step"
        if has_step:
            step = record.history.step.num
            history_dict["_step"] = step
            item.value_json = json.dumps(step)
            self._step = step + 1
        else:
            history_dict["_step"] = self._step
            item.value_json = json.dumps(self._step)
            self._step += 1

    def _history_define_metric(
        self, hkey: str
    ) -> Optional[wandb_internal_pb2.MetricRecord]:
        """check for hkey match in glob metrics, return defined metric."""
        # Dont define metric for internal metrics
        if hkey.startswith("_"):
            return None
        for k, mglob in six.iteritems(self._metric_globs):
            if k.endswith("*"):
                if hkey.startswith(k[:-1]):
                    m = wandb_internal_pb2.MetricRecord()
                    m.CopyFrom(mglob)
                    m.ClearField("glob_name")
                    m.options.defined = False
                    m.name = hkey
                    return m
        return None

    def _history_update_leaf(
        self, kl: List[str], v: Any, history_dict: Dict, update_history: Dict[str, Any]
    ) -> None:
        hkey = ".".join([k.replace(".", "\\.") for k in kl])
        m = self._metric_defines.get(hkey)
        if not m:
            m = self._history_define_metric(hkey)
            if not m:
                return
            mr = wandb_internal_pb2.Record()
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
        self, kl: List[str], v: Any, history_dict: Dict, update_history: Dict[str, Any]
    ) -> None:
        if isinstance(v, dict):
            for nk, nv in six.iteritems(v):
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

    def _history_update(self, record: Record, history_dict: Dict) -> None:
        # if syncing an old run, we can skip this logic
        if history_dict.get("_step") is None:
            self._history_assign_step(record, history_dict)

        update_history: Dict[str, Any] = {}
        # Look for metric matches
        if self._metric_defines or self._metric_globs:
            for hkey, hval in six.iteritems(history_dict):
                self._history_update_list([hkey], hval, history_dict, update_history)

        if update_history:
            history_dict.update(update_history)
            for k, v in six.iteritems(update_history):
                item = record.history.item.add()
                item.key = k
                item.value_json = json.dumps(v)

    def handle_history(self, record: Record) -> None:
        history_dict = proto_util.dict_from_proto_list(record.history.item)

        # Inject _runtime if it is not present
        if history_dict is not None:
            if "_runtime" not in history_dict:
                self._history_assign_runtime(record, history_dict)

        self._history_update(record, history_dict)
        self._dispatch_record(record)
        self._save_history(record)

        updated = self._update_summary(history_dict)
        if updated:
            self._save_summary(self._consolidated_summary)

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
        self._dispatch_record(record)

    def handle_request_log_artifact(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_telemetry(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_request_run_start(self, record: Record) -> None:
        run_start = record.request.run_start
        assert run_start
        assert run_start.run

        self._run_start_time = run_start.run.start_time.ToSeconds()

        self._track_time = time.time()
        if run_start.run.resumed and run_start.run.runtime:
            self._accumulate_time = run_start.run.runtime
        else:
            self._accumulate_time = 0

        if not self._settings._disable_stats:
            pid = os.getpid()
            self._system_stats = stats.SystemStats(pid=pid, interface=self._interface)
            self._system_stats.start()

        if not self._settings._disable_meta and not run_start.run.resumed:
            run_meta = meta.Meta(settings=self._settings, interface=self._interface)
            run_meta.probe()
            run_meta.write()

        self._tb_watcher = tb_watcher.TBWatcher(
            self._settings, interface=self._interface, run_proto=run_start.run
        )

        if run_start.run.resumed:
            self._step = run_start.run.starting_step
        result = wandb_internal_pb2.Result(uuid=record.uuid)
        self._result_q.put(result)

    def handle_request_resume(self, record: Record) -> None:
        if self._system_stats is not None:
            logger.info("starting system metrics thread")
            self._system_stats.start()

        if self._track_time is not None:
            self._accumulate_time += time.time() - self._track_time
        self._track_time = time.time()

    def handle_request_pause(self, record: Record) -> None:
        if self._system_stats is not None:
            logger.info("stopping system metrics thread")
            self._system_stats.shutdown()
        if self._track_time is not None:
            self._accumulate_time += time.time() - self._track_time
            self._track_time = None

    def handle_request_poll_exit(self, record: Record) -> None:
        self._dispatch_record(record, always_send=True)

    def handle_request_stop_status(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_request_network_status(self, record: Record) -> None:
        self._dispatch_record(record)

    def handle_request_get_summary(self, record: Record) -> None:
        result = wandb_internal_pb2.Result(uuid=record.uuid)
        for key, value in six.iteritems(self._consolidated_summary):
            item = wandb_internal_pb2.SummaryItem()
            item.key = key
            item.value_json = json.dumps(value)
            result.response.get_summary_response.item.append(item)
        self._result_q.put(result)

    def handle_tbrecord(self, record: Record) -> None:
        logger.info("handling tbrecord: %s", record)
        if self._tb_watcher:
            tbrecord = record.tbrecord
            self._tb_watcher.add(tbrecord.log_dir, tbrecord.save, tbrecord.root_dir)
        self._dispatch_record(record)

    def _handle_defined_metric(self, record: wandb_internal_pb2.Record) -> None:
        metric = record.metric
        if metric._control.overwrite:
            self._metric_defines.setdefault(
                metric.name, wandb_internal_pb2.MetricRecord()
            ).CopyFrom(metric)
        else:
            self._metric_defines.setdefault(
                metric.name, wandb_internal_pb2.MetricRecord()
            ).MergeFrom(metric)

        # before dispatching, make sure step_metric is defined, if not define it and
        # dispatch it locally first
        metric = self._metric_defines[metric.name]
        if metric.step_metric and metric.step_metric not in self._metric_defines:
            m = wandb_internal_pb2.MetricRecord(name=metric.step_metric)
            self._metric_defines[metric.step_metric] = m
            mr = wandb_internal_pb2.Record()
            mr.metric.CopyFrom(m)
            mr.control.local = True  # Dont store this, just send it
            self._dispatch_record(mr)

        self._dispatch_record(record)

    def _handle_glob_metric(self, record: wandb_internal_pb2.Record) -> None:
        metric = record.metric
        if metric._control.overwrite:
            self._metric_globs.setdefault(
                metric.glob_name, wandb_internal_pb2.MetricRecord()
            ).CopyFrom(metric)
        else:
            self._metric_globs.setdefault(
                metric.glob_name, wandb_internal_pb2.MetricRecord()
            ).MergeFrom(metric)
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
        result = wandb_internal_pb2.Result(uuid=record.uuid)
        for key, sampled in six.iteritems(self._sampled_history):
            item = wandb_internal_pb2.SampledHistoryItem()
            item.key = key
            values: Iterable[Any] = sampled.get()
            if all(isinstance(i, numbers.Integral) for i in values):
                item.values_int.extend(values)
            elif all(isinstance(i, numbers.Real) for i in values):
                item.values_float.extend(values)
            result.response.sampled_history_response.item.append(item)
        self._result_q.put(result)

    def handle_request_shutdown(self, record: Record) -> None:
        # TODO(jhr): should we drain things and stop new requests from coming in?
        result = wandb_internal_pb2.Result(uuid=record.uuid)
        self._result_q.put(result)
        self._stopped.set()

    def finish(self) -> None:
        logger.info("shutting down handler")
        if self._tb_watcher:
            self._tb_watcher.finish()

    def __next__(self) -> Record:
        return self._record_q.get(block=True)

    next = __next__

    def _history_assign_runtime(self, record: Record, history_dict: Dict) -> None:
        # _runtime calculation is meaningless if there is no _timestamp
        if "_timestamp" not in history_dict:
            return
        # if it is offline sync, self._run_start_time is 0
        # in that case set it to the first tfevent timestamp
        if self._run_start_time == 0:
            self._run_start_time = history_dict["_timestamp"]
        history_dict["_runtime"] = int(
            history_dict["_timestamp"] - self._run_start_time
        )
        item = record.history.item.add()
        item.key = "_runtime"
        item.value_json = json.dumps(history_dict[item.key])
