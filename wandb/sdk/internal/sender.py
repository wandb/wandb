#
# -*- coding: utf-8 -*-
"""
sender.
"""

from __future__ import print_function

from datetime import datetime
import json
import logging
import os
import time

from pkg_resources import parse_version
import wandb
from wandb import util
from wandb.filesync.dir_watcher import DirWatcher
from wandb.proto import wandb_internal_pb2

from . import artifacts
from . import file_stream
from . import internal_api
from . import update
from .file_pusher import FilePusher
from ..interface import interface
from ..lib import config_util, filenames, proto_util, telemetry
from ..lib.git import GitRepo


logger = logging.getLogger(__name__)

if wandb.TYPE_CHECKING:  # TYPE_CHECKING
    from typing import Any, Dict, Generator, List, NewType, Optional, Tuple

    DictWithValues = NewType("DictWithValues", Dict[str, Any])
    DictNoValues = NewType("DictNoValues", Dict[str, Any])


def _framework_priority(
    imp: telemetry.TelemetryImports,
) -> Generator[Tuple[bool, str], None, None]:
    yield imp.lightgbm, "lightgbm"
    yield imp.catboost, "catboost"
    yield imp.xgboost, "xgboost"
    yield imp.transformers, "huggingface"
    yield imp.pytorch_ignite, "ignite"
    yield imp.pytorch_lightning, "lightning"
    yield imp.fastai, "fastai"
    yield imp.torch, "torch"
    yield imp.keras, "keras"
    yield imp.tensorflow, "tensorflow"
    yield imp.sklearn, "sklearn"


class SendManager(object):

    _telemetry_obj: telemetry.TelemetryRecord

    def __init__(
        self, settings, record_q, result_q, interface,
    ):
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._interface = interface

        self._fs = None
        self._pusher = None
        self._dir_watcher = None

        # State updated by login
        self._entity = None
        self._flags = None

        # State updated by wandb.init
        self._run = None
        self._project = None

        # keep track of config from key/val updates
        self._consolidated_config: DictNoValues = dict()
        self._telemetry_obj = telemetry.TelemetryRecord()
        # TODO: remove default_xaxis
        self._config_default_xaxis: str = None
        self._config_metric_pbdict_list: List[Dict[int, Any]] = []
        self._config_metric_index_dict: Dict[str, int] = {}
        self._config_metric_dict: Dict[str, wandb_internal_pb2.MetricRecord] = {}

        # State updated by resuming
        self._resume_state = {
            "step": 0,
            "history": 0,
            "events": 0,
            "output": 0,
            "runtime": 0,
            "summary": None,
            "config": None,
            "resumed": False,
        }

        # State added when run_exit needs results
        self._exit_sync_uuid = None

        # State added when run_exit is complete
        self._exit_result = None

        self._api = internal_api.Api(default_settings=settings)
        self._api_settings = dict()

        # TODO(jhr): do something better, why do we need to send full lines?
        self._partial_output = dict()

        self._exit_code = 0

    def send(self, record):
        record_type = record.WhichOneof("record_type")
        assert record_type
        handler_str = "send_" + record_type
        send_handler = getattr(self, handler_str, None)
        # Don't log output to reduce log noise
        if record_type != "output":
            logger.debug("send: {}".format(record_type))
        assert send_handler, "unknown send handler: {}".format(handler_str)
        send_handler(record)

    def send_request(self, record):
        request_type = record.request.WhichOneof("request_type")
        assert request_type
        handler_str = "send_request_" + request_type
        send_handler = getattr(self, handler_str, None)
        logger.debug("send_request: {}".format(request_type))
        assert send_handler, "unknown handle: {}".format(handler_str)
        send_handler(record)

    def _flatten(self, dictionary):
        if type(dictionary) == dict:
            for k, v in list(dictionary.items()):
                if type(v) == dict:
                    self._flatten(v)
                    dictionary.pop(k)
                    for k2, v2 in v.items():
                        dictionary[k + "." + k2] = v2

    def send_request_check_version(self, record):
        assert record.control.req_resp
        result = wandb_internal_pb2.Result(uuid=record.uuid)
        current_version = (
            record.request.check_version.current_version or wandb.__version__
        )
        messages = update.check_available(current_version)
        if messages:
            upgrade_message = messages.get("upgrade_message")
            if upgrade_message:
                result.response.check_version_response.upgrade_message = upgrade_message
            yank_message = messages.get("yank_message")
            if yank_message:
                result.response.check_version_response.yank_message = yank_message
            delete_message = messages.get("delete_message")
            if delete_message:
                result.response.check_version_response.delete_message = delete_message
        self._result_q.put(result)

    def send_request_status(self, record):
        assert record.control.req_resp

        result = wandb_internal_pb2.Result(uuid=record.uuid)
        status_resp = result.response.status_response
        if record.request.status.check_stop_req:
            status_resp.run_should_stop = False
            if self._entity and self._project and self._run.run_id:
                try:
                    status_resp.run_should_stop = self._api.check_stop_requested(
                        self._project, self._entity, self._run.run_id
                    )
                except Exception as e:
                    logger.warning("Failed to check stop requested status: %s", e)
        self._result_q.put(result)

    def send_request_login(self, record):
        # TODO: do something with api_key or anonymous?
        # TODO: return an error if we aren't logged in?
        self._api.reauth()
        viewer_tuple = self._api.viewer_server_info()
        # self._login_flags = json.loads(viewer.get("flags", "{}"))
        # self._login_entity = viewer.get("entity")
        viewer, server_info = viewer_tuple
        if server_info:
            logger.info("Login server info: {}".format(server_info))
        self._entity = viewer.get("entity")
        if record.control.req_resp:
            result = wandb_internal_pb2.Result(uuid=record.uuid)
            if self._entity:
                result.response.login_response.active_entity = self._entity
            self._result_q.put(result)

    def send_exit(self, data):
        exit = data.exit
        self._exit_code = exit.exit_code

        logger.info("handling exit code: %s", exit.exit_code)

        # Pass the responsibility to respond to handle_request_defer()
        if data.control.req_resp:
            self._exit_sync_uuid = data.uuid

        # We need to give the request queue a chance to empty between states
        # so use handle_request_defer as a state machine.
        logger.info("send defer")
        self._interface.publish_defer()

    def send_final(self, data):
        pass

    def send_request_defer(self, data):
        defer = data.request.defer
        state = defer.state
        logger.info("handle sender defer: {}".format(state))

        done = False
        if state == defer.BEGIN:
            pass
        elif state == defer.FLUSH_STATS:
            # NOTE: this is handled in handler.py:handle_request_defer()
            pass
        elif state == defer.FLUSH_TB:
            # NOTE: this is handled in handler.py:handle_request_defer()
            pass
        elif state == defer.FLUSH_SUM:
            # NOTE: this is handled in handler.py:handle_request_defer()
            pass
        elif state == defer.FLUSH_DIR:
            if self._dir_watcher:
                self._dir_watcher.finish()
                self._dir_watcher = None
        elif state == defer.FLUSH_FP:
            if self._pusher:
                self._pusher.finish()
        elif state == defer.FLUSH_FS:
            if self._fs:
                # TODO(jhr): now is a good time to output pending output lines
                self._fs.finish(self._exit_code)
                self._fs = None
        elif state == defer.FLUSH_FINAL:
            self._interface.publish_final()
            self._interface.publish_footer()
        elif state == defer.END:
            done = True
        else:
            raise AssertionError("unknown state")

        if not done:
            state += 1
            logger.info("send defer: {}".format(state))
            self._interface.publish_defer(state)
            return

        exit_result = wandb_internal_pb2.RunExitResult()

        # This path is not the prefered method to return exit results
        # as it could take a long time to flush the file pusher buffers
        if self._exit_sync_uuid:
            if self._pusher:
                # NOTE: This will block until finished
                self._pusher.print_status()
                self._pusher.join()
                self._pusher = None
            resp = wandb_internal_pb2.Result(
                exit_result=exit_result, uuid=self._exit_sync_uuid
            )
            self._result_q.put(resp)

        # mark exit done in case we are polling on exit
        self._exit_result = exit_result

    def send_request_poll_exit(self, record):
        if not record.control.req_resp:
            return

        result = wandb_internal_pb2.Result(uuid=record.uuid)

        alive = False
        if self._pusher:
            alive, status = self._pusher.get_status()
            file_counts = self._pusher.file_counts_by_category()
            resp = result.response.poll_exit_response
            resp.pusher_stats.uploaded_bytes = status["uploaded_bytes"]
            resp.pusher_stats.total_bytes = status["total_bytes"]
            resp.pusher_stats.deduped_bytes = status["deduped_bytes"]
            resp.file_counts.wandb_count = file_counts["wandb"]
            resp.file_counts.media_count = file_counts["media"]
            resp.file_counts.artifact_count = file_counts["artifact"]
            resp.file_counts.other_count = file_counts["other"]

        if self._exit_result and not alive:
            # pusher join should not block as it was reported as not alive
            if self._pusher:
                self._pusher.join()
            result.response.poll_exit_response.exit_result.CopyFrom(self._exit_result)
            result.response.poll_exit_response.done = True
        self._result_q.put(result)

    def _maybe_setup_resume(self, run) -> "Optional[wandb_internal_pb2.ErrorInfo]":
        """This maybe queries the backend for a run and fails if the settings are
        incompatible."""
        if not self._settings.resume:
            return None

        # TODO: This causes a race, we need to make the upsert atomically
        # only create or update depending on the resume config
        # we use the runs entity if set, otherwise fallback to users entity
        entity = run.entity or self._entity
        logger.info(
            "checking resume status for %s/%s/%s", entity, run.project, run.run_id
        )
        resume_status = self._api.run_resume_status(
            entity=entity, project_name=run.project, name=run.run_id
        )

        if not resume_status:
            if self._settings.resume == "must":
                error = wandb_internal_pb2.ErrorInfo()
                error.code = wandb_internal_pb2.ErrorInfo.ErrorCode.INVALID
                error.message = "resume='must' but run (%s) doesn't exist" % run.run_id
                return error
            return None

        #
        # handle cases where we have resume_status
        #
        if self._settings.resume == "never":
            error = wandb_internal_pb2.ErrorInfo()
            error.code = wandb_internal_pb2.ErrorInfo.ErrorCode.INVALID
            error.message = "resume='never' but run (%s) exists" % run.run_id
            return error

        history = {}
        events = {}
        config = {}
        summary = {}
        try:
            events_rt = 0
            history_rt = 0
            history = json.loads(resume_status["historyTail"])
            if history:
                history = json.loads(history[-1])
                history_rt = history.get("_runtime", 0)
            events = json.loads(resume_status["eventsTail"])
            if events:
                events = json.loads(events[-1])
                events_rt = events.get("_runtime", 0)
            config = json.loads(resume_status["config"] or "{}")
            summary = json.loads(resume_status["summaryMetrics"] or "{}")
        except (IndexError, ValueError) as e:
            logger.error("unable to load resume tails", exc_info=e)
            if self._settings.resume == "must":
                error = wandb_internal_pb2.ErrorInfo()
                error.code = wandb_internal_pb2.ErrorInfo.ErrorCode.INVALID
                error.message = "resume='must' but could not resume (%s) " % run.run_id
                return error

        # TODO: Do we need to restore config / summary?
        # System metrics runtime is usually greater than history
        self._resume_state["runtime"] = max(events_rt, history_rt)
        self._resume_state["step"] = history.get("_step", -1) + 1 if history else 0
        self._resume_state["history"] = resume_status["historyLineCount"]
        self._resume_state["events"] = resume_status["eventsLineCount"]
        self._resume_state["output"] = resume_status["logLineCount"]
        self._resume_state["config"] = config
        self._resume_state["summary"] = summary
        self._resume_state["resumed"] = True
        logger.info("configured resuming with: %s" % self._resume_state)
        return None

    def _telemetry_get_framework(self) -> str:
        """Get telemetry data for internal config structure."""
        # detect framework by checking what is loaded
        imp: telemetry.TelemetryImports
        if self._telemetry_obj.HasField("imports_finish"):
            imp = self._telemetry_obj.imports_finish
        elif self._telemetry_obj.HasField("imports_init"):
            imp = self._telemetry_obj.imports_init
        else:
            return ""
        priority = _framework_priority(imp)
        framework = next((f for b, f in priority if b), "")
        return framework

    def _config_telemetry_update(self, config_dict: Dict[str, Any]) -> None:
        """Add legacy telemetry to config object."""
        wandb_key = "_wandb"
        config_dict.setdefault(wandb_key, dict())
        s: str
        b: bool
        s = self._telemetry_obj.python_version
        if s:
            config_dict[wandb_key]["python_version"] = s
        s = self._telemetry_obj.cli_version
        if s:
            config_dict[wandb_key]["cli_version"] = s
        s = self._telemetry_get_framework()
        if s:
            config_dict[wandb_key]["framework"] = s
        s = self._telemetry_obj.huggingface_version
        if s:
            config_dict[wandb_key]["huggingface_version"] = s
        b = self._telemetry_obj.env.jupyter
        config_dict[wandb_key]["is_jupyter_run"] = b
        b = self._telemetry_obj.env.kaggle
        config_dict[wandb_key]["is_kaggle_kernel"] = b

        t: Dict[int, Any] = proto_util.proto_encode_to_dict(self._telemetry_obj)
        config_dict[wandb_key]["t"] = t

    def _config_metric_update(self, config_dict: Dict[str, Any]) -> None:
        """Add default xaxis to config."""
        if not self._config_metric_pbdict_list:
            return
        wandb_key = "_wandb"
        config_dict.setdefault(wandb_key, dict())
        # TODO(jhr): remove this
        if self._config_default_xaxis:
            config_dict[wandb_key]["x_axis"] = self._config_default_xaxis
        config_dict[wandb_key]["m"] = self._config_metric_pbdict_list

    def _config_format(self, config_data: Optional[DictNoValues]) -> DictWithValues:
        """Format dict into value dict with telemetry info."""
        config_dict: Dict[str, Any] = config_data.copy() if config_data else dict()
        self._config_telemetry_update(config_dict)
        self._config_metric_update(config_dict)
        config_value_dict: DictWithValues = config_util.dict_add_value_dict(config_dict)
        return config_value_dict

    def _config_save(self, config_value_dict: DictWithValues) -> None:
        config_path = os.path.join(self._settings.files_dir, "config.yaml")
        config_util.save_config_file_from_dict(config_path, config_value_dict)

    def send_run(self, data) -> None:
        run = data.run
        error = None
        is_wandb_init = self._run is None

        # update telemetry
        if run.telemetry:
            self._telemetry_obj.MergeFrom(run.telemetry)

        # build config dict
        config_value_dict: Optional[DictWithValues] = None
        if run.config:
            config_util.update_from_proto(self._consolidated_config, run.config)
            config_value_dict = self._config_format(self._consolidated_config)
            self._config_save(config_value_dict)

        if is_wandb_init:
            # Ensure we have a project to query for status
            if run.project == "":
                run.project = util.auto_project_name(self._settings.program)
            # Only check resume status on `wandb.init`
            error = self._maybe_setup_resume(run)

        if error is not None:
            if data.control.req_resp:
                resp = wandb_internal_pb2.Result(uuid=data.uuid)
                resp.run_result.run.CopyFrom(run)
                resp.run_result.error.CopyFrom(error)
                self._result_q.put(resp)
            else:
                logger.error("Got error in async mode: %s", error.message)
            return

        # Save the resumed config
        if self._resume_state["config"] is not None:
            # TODO: should we merge this with resumed config?
            config_override = self._consolidated_config
            config_dict = self._resume_state["config"]
            config_dict = config_util.dict_strip_value_dict(config_dict)
            config_dict.update(config_override)
            self._consolidated_config.update(config_dict)
            config_value_dict = self._config_format(self._consolidated_config)
            self._config_save(config_value_dict)

        # handle empty config
        # TODO(jhr): consolidate the 4 ways config is built:
        #            (passed config, empty config, resume config, send_config)
        if not config_value_dict:
            config_value_dict = self._config_format(None)
            self._config_save(config_value_dict)

        self._init_run(run, config_value_dict)

        if data.control.req_resp:
            resp = wandb_internal_pb2.Result(uuid=data.uuid)
            # TODO: we could do self._interface.publish_defer(resp) to notify
            # the handler not to actually perform server updates for this uuid
            # because the user process will send a summary update when we resume
            resp.run_result.run.CopyFrom(self._run)
            self._result_q.put(resp)

        # Only spin up our threads on the first run message
        if is_wandb_init:
            self._start_run_threads()
        else:
            logger.info("updated run: %s", self._run.run_id)

    def _init_run(self, run, config_dict):
        # We subtract the previous runs runtime when resuming
        start_time = run.start_time.ToSeconds() - self._resume_state["runtime"]
        repo = GitRepo(remote=self._settings.git_remote)
        # TODO: we don't check inserted currently, ultimately we should make
        # the upsert know the resume state and fail transactionally
        server_run, inserted = self._api.upsert_run(
            name=run.run_id,
            entity=run.entity or None,
            project=run.project or None,
            group=run.run_group or None,
            job_type=run.job_type or None,
            display_name=run.display_name or None,
            notes=run.notes or None,
            tags=run.tags[:] or None,
            config=config_dict or None,
            sweep_name=run.sweep_id or None,
            host=run.host or None,
            program_path=self._settings.program or None,
            repo=repo.remote_url,
            commit=repo.last_commit,
        )
        self._run = run
        if self._resume_state.get("resumed"):
            self._run.resumed = True
        self._run.starting_step = self._resume_state["step"]
        self._run.start_time.FromSeconds(int(start_time))
        self._run.config.CopyFrom(self._interface._make_config(config_dict))
        if self._resume_state["summary"] is not None:
            self._run.summary.CopyFrom(
                self._interface._make_summary_from_dict(self._resume_state["summary"])
            )
        storage_id = server_run.get("id")
        if storage_id:
            self._run.storage_id = storage_id
        id = server_run.get("name")
        if id:
            self._api.set_current_run_id(id)
        display_name = server_run.get("displayName")
        if display_name:
            self._run.display_name = display_name
        project = server_run.get("project")
        # TODO: remove self._api.set_settings, and make self._project a property?
        if project:
            project_name = project.get("name")
            if project_name:
                self._run.project = project_name
                self._project = project_name
                self._api_settings["project"] = project_name
                self._api.set_setting("project", project_name)
            entity = project.get("entity")
            if entity:
                entity_name = entity.get("name")
                if entity_name:
                    self._run.entity = entity_name
                    self._entity = entity_name
                    self._api_settings["entity"] = entity_name
                    self._api.set_setting("entity", entity_name)
        sweep_id = server_run.get("sweepName")
        if sweep_id:
            self._run.sweep_id = sweep_id

    def _start_run_threads(self):
        self._fs = file_stream.FileStreamApi(
            self._api,
            self._run.run_id,
            self._run.start_time.ToSeconds(),
            settings=self._api_settings,
        )
        # Ensure the streaming polices have the proper offsets
        self._fs.set_file_policy("wandb-summary.json", file_stream.SummaryFilePolicy())
        self._fs.set_file_policy(
            "wandb-history.jsonl",
            file_stream.JsonlFilePolicy(start_chunk_id=self._resume_state["history"]),
        )
        self._fs.set_file_policy(
            "wandb-events.jsonl",
            file_stream.JsonlFilePolicy(start_chunk_id=self._resume_state["events"]),
        )
        self._fs.set_file_policy(
            "output.log",
            file_stream.CRDedupeFilePolicy(start_chunk_id=self._resume_state["output"]),
        )
        self._fs.start()
        self._pusher = FilePusher(self._api, silent=self._settings.silent)
        self._dir_watcher = DirWatcher(self._settings, self._api, self._pusher)
        util.sentry_set_scope(
            "internal",
            entity=self._run.entity,
            project=self._run.project,
            email=self._settings.email,
        )
        logger.info(
            "run started: %s with start time %s",
            self._run.run_id,
            self._run.start_time.ToSeconds(),
        )

    def _save_history(self, history_dict):
        if self._fs:
            self._fs.push(filenames.HISTORY_FNAME, json.dumps(history_dict))

    def send_history(self, data):
        history = data.history
        history_dict = proto_util.dict_from_proto_list(history.item)
        self._save_history(history_dict)

    def send_summary(self, data):
        summary_dict = proto_util.dict_from_proto_list(data.summary.update)
        json_summary = json.dumps(summary_dict)
        if self._fs:
            self._fs.push(filenames.SUMMARY_FNAME, json_summary)
        # TODO(jhr): we should only write this at the end of the script
        summary_path = os.path.join(self._settings.files_dir, filenames.SUMMARY_FNAME)
        with open(summary_path, "w") as f:
            f.write(json_summary)
        self._save_file(filenames.SUMMARY_FNAME)

    def send_stats(self, data):
        stats = data.stats
        if stats.stats_type != wandb_internal_pb2.StatsRecord.StatsType.SYSTEM:
            return
        if not self._fs:
            return
        now = stats.timestamp.seconds
        d = dict()
        for item in stats.item:
            d[item.key] = json.loads(item.value_json)
        row = dict(system=d)
        self._flatten(row)
        row["_wandb"] = True
        row["_timestamp"] = now
        row["_runtime"] = int(now - self._run.start_time.ToSeconds())
        self._fs.push(filenames.EVENTS_FNAME, json.dumps(row))
        # TODO(jhr): check fs.push results?

    def send_output(self, data):
        if not self._fs:
            return
        out = data.output
        prepend = ""
        stream = "stdout"
        if out.output_type == wandb_internal_pb2.OutputRecord.OutputType.STDERR:
            stream = "stderr"
            prepend = "ERROR "
        line = out.line
        if not line.endswith("\n"):
            self._partial_output.setdefault(stream, "")
            self._partial_output[stream] += line
            # TODO(jhr): how do we make sure this gets flushed?
            # we might need this for other stuff like telemetry
        else:
            # TODO(jhr): use time from timestamp proto
            # TODO(jhr): do we need to make sure we write full lines?
            # seems to be some issues with line breaks
            cur_time = time.time()
            timestamp = datetime.utcfromtimestamp(cur_time).isoformat() + " "
            prev_str = self._partial_output.get(stream, "")
            line = u"{}{}{}{}".format(prepend, timestamp, prev_str, line)
            self._fs.push(filenames.OUTPUT_FNAME, line)
            self._partial_output[stream] = ""

    def _update_config(self):
        config_value_dict = self._config_format(self._consolidated_config)
        self._api.upsert_run(
            name=self._run.run_id, config=config_value_dict, **self._api_settings
        )
        self._config_save(config_value_dict)
        # TODO(jhr): check result of upsert_run?

    def send_config(self, data):
        cfg = data.config
        config_util.update_from_proto(self._consolidated_config, cfg)
        self._update_config()

    def send_metric(self, data: wandb_internal_pb2.Record) -> None:
        metric = data.metric
        if metric.glob_name:
            logger.warning("Seen metric with glob (shouldnt happen)")
            return

        # merge or overwrite
        old_metric = self._config_metric_dict.get(
            metric.name, wandb_internal_pb2.MetricRecord()
        )
        if metric._control.overwrite:
            old_metric.CopyFrom(metric)
        else:
            old_metric.MergeFrom(metric)
        self._config_metric_dict[metric.name] = old_metric
        metric = old_metric

        # TODO(jhr): remove this code before shipping (only for prototype UI)
        if metric.step_metric:
            if metric.step_metric != self._config_default_xaxis:
                self._config_default_xaxis = metric.step_metric
                self._update_config()

        # convert step_metric to index
        if metric.step_metric:
            find_step_idx = self._config_metric_index_dict.get(metric.step_metric)
            if find_step_idx is not None:
                # make a copy of this metric as we will be modifying it
                rec = wandb_internal_pb2.Record()
                rec.metric.CopyFrom(metric)
                metric = rec.metric

                metric.ClearField("step_metric")
                metric.step_metric_index = find_step_idx + 1

        md: Dict[int, Any] = proto_util.proto_encode_to_dict(metric)
        find_idx = self._config_metric_index_dict.get(metric.name)
        if find_idx is not None:
            self._config_metric_pbdict_list[find_idx] = md
        else:
            next_idx = len(self._config_metric_pbdict_list)
            self._config_metric_pbdict_list.append(md)
            self._config_metric_index_dict[metric.name] = next_idx
        self._update_config()

    def send_telemetry(self, data):
        telem = data.telemetry
        self._telemetry_obj.MergeFrom(telem)
        self._update_config()

    def _save_file(self, fname, policy="end"):
        logger.info("saving file %s with policy %s", fname, policy)
        if self._dir_watcher:
            self._dir_watcher.update_policy(fname, policy)

    def send_files(self, data):
        files = data.files
        for k in files.files:
            # TODO(jhr): fix paths with directories
            self._save_file(k.path, interface.file_enum_to_policy(k.policy))

    def send_header(self, data):
        pass

    def send_footer(self, data):
        pass

    def send_tbrecord(self, data):
        # tbrecord watching threads are handled by handler.py
        pass

    def send_request_log_artifact(self, record):
        assert record.control.req_resp
        result = wandb_internal_pb2.Result(uuid=record.uuid)
        artifact = record.request.log_artifact.artifact

        try:
            result.response.log_artifact_response.artifact_id = self._send_artifact(
                artifact
            ).get("id")
        except Exception as e:
            result.response.log_artifact_response.error_message = 'error logging artifact "{}/{}": {}'.format(
                artifact.type, artifact.name, e
            )

        self._result_q.put(result)

    def send_artifact(self, data):
        artifact = data.artifact
        try:
            self._send_artifact(artifact)
        except Exception as e:
            logger.error(
                'send_artifact: failed for artifact "{}/{}": {}'.format(
                    artifact.type, artifact.name, e
                )
            )

    def _send_artifact(self, artifact):
        saver = artifacts.ArtifactSaver(
            api=self._api,
            digest=artifact.digest,
            manifest_json=artifacts._manifest_json_from_proto(artifact.manifest),
            file_pusher=self._pusher,
            is_user_created=artifact.user_created,
        )

        if artifact.distributed_id:
            max_cli_version = self._max_cli_version()
            if max_cli_version is None or parse_version(
                max_cli_version
            ) < parse_version("0.10.16"):
                logger.warning(
                    "This W&B server doesn't support distributed artifacts, "
                    "have your administrator install wandb/local >= 0.9.37"
                )
                return

        metadata = json.loads(artifact.metadata) if artifact.metadata else None
        return saver.save(
            type=artifact.type,
            name=artifact.name,
            metadata=metadata,
            description=artifact.description,
            aliases=artifact.aliases,
            use_after_commit=artifact.use_after_commit,
            distributed_id=artifact.distributed_id,
            finalize=artifact.finalize,
        )

    def send_alert(self, data):
        alert = data.alert
        max_cli_version = self._max_cli_version()
        if max_cli_version is None or parse_version(max_cli_version) < parse_version(
            "0.10.9"
        ):
            logger.warning(
                "This W&B server doesn't support alerts, "
                "have your administrator install wandb/local >= 0.9.31"
            )
        else:
            try:
                self._api.notify_scriptable_run_alert(
                    title=alert.title,
                    text=alert.text,
                    level=alert.level,
                    wait_duration=alert.wait_duration,
                )
            except Exception as e:
                logger.error(
                    'send_alert: failed for alert "{}": {}'.format(alert.title, e)
                )

    def finish(self):
        logger.info("shutting down sender")
        # if self._tb_watcher:
        #     self._tb_watcher.finish()
        if self._dir_watcher:
            self._dir_watcher.finish()
            self._dir_watcher = None
        if self._pusher:
            self._pusher.finish()
            self._pusher.join()
            self._pusher = None
        if self._fs:
            self._fs.finish(self._exit_code)
            self._fs = None

    def _max_cli_version(self):
        _, server_info = self._api.viewer_server_info()
        max_cli_version = server_info.get("cliVersionInfo", {}).get(
            "max_cli_version", None
        )
        return max_cli_version
