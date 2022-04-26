"""
sender.
"""


from collections import defaultdict
from datetime import datetime
import json
import logging
import os
import queue
from queue import Queue
import time
from typing import Any, Dict, Generator, List, NewType, Optional, Tuple
from typing import cast, TYPE_CHECKING

from pkg_resources import parse_version
import requests
import wandb
from wandb import util
from wandb.filesync.dir_watcher import DirWatcher
from wandb.proto import wandb_internal_pb2

from . import artifacts
from . import file_stream
from . import internal_api
from . import update
from .file_pusher import FilePusher
from .settings_static import SettingsDict, SettingsStatic
from ..interface import interface
from ..interface.interface_queue import InterfaceQueue
from ..lib import config_util, filenames, proto_util, telemetry
from ..lib import tracelog
from ..lib.proto_util import message_to_dict

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import (
        ArtifactRecord,
        HttpResponse,
        LocalInfo,
        Record,
        Result,
        RunExitResult,
        RunRecord,
    )


logger = logging.getLogger(__name__)


DictWithValues = NewType("DictWithValues", Dict[str, Any])
DictNoValues = NewType("DictNoValues", Dict[str, Any])


def _framework_priority(
    imp: telemetry.TelemetryImports,
) -> Generator[Tuple[bool, str], None, None]:
    yield imp.lightgbm, "lightgbm"
    yield imp.catboost, "catboost"
    yield imp.xgboost, "xgboost"
    yield imp.transformers_huggingface, "huggingface"
    yield imp.pytorch_ignite, "ignite"
    yield imp.pytorch_lightning, "lightning"
    yield imp.fastai, "fastai"
    yield imp.torch, "torch"
    yield imp.keras, "keras"
    yield imp.tensorflow, "tensorflow"
    yield imp.sklearn, "sklearn"


class ResumeState:
    resumed: bool
    step: int
    history: int
    events: int
    output: int
    runtime: int
    wandb_runtime: Optional[int]
    summary: Optional[Dict[str, Any]]
    config: Optional[Dict[str, Any]]

    def __init__(self) -> None:
        self.resumed = False
        self.step = 0
        self.history = 0
        self.events = 0
        self.output = 0
        self.runtime = 0
        # wandb_runtime is the canonical runtime (stored in summary._wandb.runtime)
        self.wandb_runtime = None
        self.summary = None
        self.config = None

    def __str__(self) -> str:
        obj = ",".join(map(lambda it: f"{it[0]}={it[1]}", vars(self).items()))
        return f"ResumeState({obj})"


class SendManager:

    _settings: SettingsStatic
    _record_q: "Queue[Record]"
    _result_q: "Queue[Result]"
    _interface: InterfaceQueue
    _api_settings: Dict[str, str]
    _partial_output: Dict[str, str]

    _telemetry_obj: telemetry.TelemetryRecord
    _fs: "Optional[file_stream.FileStreamApi]"
    _run: "Optional[RunRecord]"
    _entity: "Optional[str]"
    _project: "Optional[str]"
    _dir_watcher: "Optional[DirWatcher]"
    _pusher: "Optional[FilePusher]"
    _exit_result: "Optional[RunExitResult]"
    _resume_state: ResumeState
    _cached_server_info: Dict[str, Any]
    _cached_viewer: Dict[str, Any]

    def __init__(
        self,
        settings: SettingsStatic,
        record_q: "Queue[Record]",
        result_q: "Queue[Result]",
        interface: InterfaceQueue,
    ) -> None:
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
        self._consolidated_config: DictNoValues = cast(DictNoValues, dict())
        self._start_time: int = 0
        self._telemetry_obj = telemetry.TelemetryRecord()
        self._config_metric_pbdict_list: List[Dict[int, Any]] = []
        self._metadata_summary: Dict[str, Any] = defaultdict()
        self._cached_summary: Dict[str, Any] = dict()
        self._config_metric_index_dict: Dict[str, int] = {}
        self._config_metric_dict: Dict[str, wandb_internal_pb2.MetricRecord] = {}

        self._cached_server_info = dict()
        self._cached_viewer = dict()

        # State updated by resuming
        self._resume_state = ResumeState()

        # State added when run_exit is complete
        self._exit_result = None

        self._api = internal_api.Api(
            default_settings=settings, retry_callback=self.retry_callback
        )
        self._api_settings = dict()

        # queue filled by retry_callback
        self._retry_q: "Queue[HttpResponse]" = queue.Queue()

        # do we need to debounce?
        self._config_needs_debounce: bool = False

        # TODO(jhr): do something better, why do we need to send full lines?
        self._partial_output = dict()

        self._exit_code = 0

    @classmethod
    def setup(cls, root_dir: str) -> "SendManager":
        """This is a helper class method to set up a standalone SendManager.
        Currently, we're using this primarily for `sync.py`.
        """
        files_dir = os.path.join(root_dir, "files")
        sd: SettingsDict = dict(
            files_dir=files_dir,
            root_dir=root_dir,
            _start_time=0,
            git_remote=None,
            resume=None,
            program=None,
            ignore_globs=(),
            run_id=None,
            entity=None,
            project=None,
            run_group=None,
            job_type=None,
            run_tags=None,
            run_name=None,
            run_notes=None,
            save_code=None,
            email=None,
            silent=None,
        )
        settings = SettingsStatic(sd)
        record_q: "Queue[Record]" = queue.Queue()
        result_q: "Queue[Result]" = queue.Queue()
        publish_interface = InterfaceQueue(record_q=record_q)
        return SendManager(
            settings=settings,
            record_q=record_q,
            result_q=result_q,
            interface=publish_interface,
        )

    def __len__(self) -> int:
        return self._record_q.qsize()

    def retry_callback(self, status: int, response_text: str) -> None:
        response = wandb_internal_pb2.HttpResponse()
        response.http_status_code = status
        response.http_response_text = response_text
        self._retry_q.put(response)

    def send(self, record: "Record") -> None:
        record_type = record.WhichOneof("record_type")
        assert record_type
        handler_str = "send_" + record_type
        send_handler = getattr(self, handler_str, None)
        # Don't log output to reduce log noise
        if record_type not in {"output", "request"}:
            logger.debug(f"send: {record_type}")
        assert send_handler, f"unknown send handler: {handler_str}"
        send_handler(record)

    def send_preempting(self, record: "Record") -> None:
        if self._fs:
            self._fs.enqueue_preempting()

    def send_request(self, record: "Record") -> None:
        request_type = record.request.WhichOneof("request_type")
        assert request_type
        handler_str = "send_request_" + request_type
        send_handler = getattr(self, handler_str, None)
        if request_type != "network_status":
            logger.debug(f"send_request: {request_type}")
        assert send_handler, f"unknown handle: {handler_str}"
        send_handler(record)

    def _respond_result(self, result: "Result") -> None:
        tracelog.log_message_queue(result, self._result_q)
        self._result_q.put(result)

    def _flatten(self, dictionary: Dict) -> None:
        if type(dictionary) == dict:
            for k, v in list(dictionary.items()):
                if type(v) == dict:
                    self._flatten(v)
                    dictionary.pop(k)
                    for k2, v2 in v.items():
                        dictionary[k + "." + k2] = v2

    def send_request_check_version(self, record: "Record") -> None:
        assert record.control.req_resp
        result = proto_util._result_from_record(record)
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
        self._respond_result(result)

    def _send_request_attach(
        self,
        req: wandb_internal_pb2.AttachRequest,
        resp: wandb_internal_pb2.AttachResponse,
    ) -> None:
        attach_id = req.attach_id
        assert attach_id
        assert self._run
        resp.run.CopyFrom(self._run)

    def send_request_attach(self, record: "Record") -> None:
        assert record.control.req_resp
        result = proto_util._result_from_record(record)
        self._send_request_attach(
            record.request.attach, result.response.attach_response
        )
        self._respond_result(result)

    def send_request_stop_status(self, record: "Record") -> None:
        assert record.control.req_resp

        result = proto_util._result_from_record(record)
        status_resp = result.response.stop_status_response
        status_resp.run_should_stop = False
        if self._entity and self._project and self._run and self._run.run_id:
            try:
                status_resp.run_should_stop = self._api.check_stop_requested(
                    self._project, self._entity, self._run.run_id
                )
            except Exception as e:
                logger.warning("Failed to check stop requested status: %s", e)
        self._respond_result(result)

    def debounce(self) -> None:
        if self._config_needs_debounce:
            self._debounce_config()

    def _debounce_config(self) -> None:
        config_value_dict = self._config_format(self._consolidated_config)
        # TODO(jhr): check result of upsert_run?
        if self._run:
            self._api.upsert_run(
                name=self._run.run_id, config=config_value_dict, **self._api_settings
            )
        self._config_save(config_value_dict)
        self._config_needs_debounce = False

    def send_request_status(self, record: "Record") -> None:
        assert record.control.req_resp
        result = proto_util._result_from_record(record)
        self._respond_result(result)

    def send_request_network_status(self, record: "Record") -> None:
        assert record.control.req_resp

        result = proto_util._result_from_record(record)
        status_resp = result.response.network_status_response
        while True:
            try:
                status_resp.network_responses.append(self._retry_q.get_nowait())
            except queue.Empty:
                break
            except Exception as e:
                logger.warning(f"Error emptying retry queue: {e}")
        self._respond_result(result)

    def send_request_login(self, record: "Record") -> None:
        # TODO: do something with api_key or anonymous?
        # TODO: return an error if we aren't logged in?
        self._api.reauth()
        viewer = self.get_viewer_info()
        server_info = self.get_server_info()
        # self._login_flags = json.loads(viewer.get("flags", "{}"))
        # self._login_entity = viewer.get("entity")
        if server_info:
            logger.info(f"Login server info: {server_info}")
        self._entity = viewer.get("entity")
        if record.control.req_resp:
            result = proto_util._result_from_record(record)
            if self._entity:
                result.response.login_response.active_entity = self._entity
            self._respond_result(result)

    def send_exit(self, record: "Record") -> None:
        exit = record.exit
        self._exit_code = exit.exit_code
        logger.info("handling exit code: %s", exit.exit_code)
        runtime = exit.runtime
        logger.info("handling runtime: %s", exit.runtime)
        self._metadata_summary["runtime"] = runtime
        self._update_summary()

        # We need to give the request queue a chance to empty between states
        # so use handle_request_defer as a state machine.
        logger.info("send defer")
        self._interface.publish_defer()

    def send_final(self, record: "Record") -> None:
        pass

    def send_request_defer(self, record: "Record") -> None:
        defer = record.request.defer
        state = defer.state
        logger.info(f"handle sender defer: {state}")

        def transition_state() -> None:
            state = defer.state + 1
            logger.info(f"send defer: {state}")
            self._interface.publish_defer(state)

        done = False
        if state == defer.BEGIN:
            transition_state()
        elif state == defer.FLUSH_STATS:
            # NOTE: this is handled in handler.py:handle_request_defer()
            transition_state()
        elif state == defer.FLUSH_PARTIAL_HISTORY:
            # NOTE: this is handled in handler.py:handle_request_defer()
            transition_state()
        elif state == defer.FLUSH_TB:
            # NOTE: this is handled in handler.py:handle_request_defer()
            transition_state()
        elif state == defer.FLUSH_SUM:
            # NOTE: this is handled in handler.py:handle_request_defer()
            transition_state()
        elif state == defer.FLUSH_DEBOUNCER:
            self.debounce()
            transition_state()
        elif state == defer.FLUSH_DIR:
            if self._dir_watcher:
                self._dir_watcher.finish()
                self._dir_watcher = None
            transition_state()
        elif state == defer.FLUSH_FP:
            if self._pusher:
                # FilePusher generates some events for FileStreamApi, so we
                # need to wait for pusher to finish before going to the next
                # state to ensure that filestream gets all the events that we
                # want before telling it to finish up
                self._pusher.finish(transition_state)
            else:
                transition_state()
        elif state == defer.FLUSH_FS:
            if self._fs:
                # TODO(jhr): now is a good time to output pending output lines
                self._fs.finish(self._exit_code)
                self._fs = None
            transition_state()
        elif state == defer.FLUSH_FINAL:
            self._interface.publish_final()
            self._interface.publish_footer()
            transition_state()
        elif state == defer.END:
            done = True
        else:
            raise AssertionError("unknown state")

        if not done:
            return

        exit_result = wandb_internal_pb2.RunExitResult()

        # mark exit done in case we are polling on exit
        self._exit_result = exit_result

    def send_request_poll_exit(self, record: "Record") -> None:
        if not record.control.req_resp:
            return

        result = proto_util._result_from_record(record)

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
            result.response.poll_exit_response.local_info.CopyFrom(
                self.get_local_info()
            )
            result.response.poll_exit_response.done = True
        self._respond_result(result)

    def _maybe_setup_resume(
        self, run: "RunRecord"
    ) -> "Optional[wandb_internal_pb2.ErrorInfo]":
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
            new_runtime = summary.get("_wandb", {}).get("runtime", None)
            if new_runtime is not None:
                self._resume_state.wandb_runtime = new_runtime

        except (IndexError, ValueError) as e:
            logger.error("unable to load resume tails", exc_info=e)
            if self._settings.resume == "must":
                error = wandb_internal_pb2.ErrorInfo()
                error.code = wandb_internal_pb2.ErrorInfo.ErrorCode.INVALID
                error.message = "resume='must' but could not resume (%s) " % run.run_id
                return error

        # TODO: Do we need to restore config / summary?
        # System metrics runtime is usually greater than history
        self._resume_state.runtime = max(events_rt, history_rt)
        self._resume_state.step = history.get("_step", -1) + 1 if history else 0
        self._resume_state.history = resume_status["historyLineCount"]
        self._resume_state.events = resume_status["eventsLineCount"]
        self._resume_state.output = resume_status["logLineCount"]
        self._resume_state.config = config
        self._resume_state.summary = summary
        self._resume_state.resumed = True
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

        config_dict[wandb_key]["start_time"] = self._start_time

        t: Dict[int, Any] = proto_util.proto_encode_to_dict(self._telemetry_obj)
        config_dict[wandb_key]["t"] = t

    def _config_metric_update(self, config_dict: Dict[str, Any]) -> None:
        """Add default xaxis to config."""
        if not self._config_metric_pbdict_list:
            return
        wandb_key = "_wandb"
        config_dict.setdefault(wandb_key, dict())
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

    def _sync_spell(self) -> None:
        """Syncs this run with spell"""
        if not self._run:
            return
        try:
            env = os.environ
            self._interface.publish_config(
                key=("_wandb", "spell_url"), val=env.get("SPELL_RUN_URL")
            )
            url = "{}/{}/{}/runs/{}".format(
                self._api.app_url, self._run.entity, self._run.project, self._run.run_id
            )
            requests.put(
                env.get("SPELL_API_URL", "https://api.spell.run") + "/wandb_url",
                json={"access_token": env.get("WANDB_ACCESS_TOKEN"), "url": url},
                timeout=2,
            )
        except requests.RequestException:
            pass
        # TODO: do something if sync spell is not successful?

    def send_run(self, record: "Record", file_dir: str = None) -> None:
        run = record.run
        error = None
        is_wandb_init = self._run is None

        # save start time of a run
        self._start_time = run.start_time.seconds

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
            if record.control.req_resp:
                result = proto_util._result_from_record(record)
                result.run_result.run.CopyFrom(run)
                result.run_result.error.CopyFrom(error)
                self._respond_result(result)
            else:
                logger.error("Got error in async mode: %s", error.message)
            return

        # Save the resumed config
        if self._resume_state.config is not None:
            # TODO: should we merge this with resumed config?
            config_override = self._consolidated_config
            config_dict = self._resume_state.config
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
        assert self._run  # self._run is configured in _init_run()

        if record.control.req_resp:
            result = proto_util._result_from_record(record)
            # TODO: we could do self._interface.publish_defer(resp) to notify
            # the handler not to actually perform server updates for this uuid
            # because the user process will send a summary update when we resume
            result.run_result.run.CopyFrom(self._run)
            self._respond_result(result)

        # Only spin up our threads on the first run message
        if is_wandb_init:
            self._start_run_threads(file_dir)
        else:
            logger.info("updated run: %s", self._run.run_id)

    def _init_run(
        self, run: "RunRecord", config_dict: Optional[DictWithValues]
    ) -> None:
        # We subtract the previous runs runtime when resuming
        start_time = run.start_time.ToSeconds() - self._resume_state.runtime
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
            repo=run.git.remote_url or None,
            commit=run.git.last_commit or None,
        )
        self._run = run
        if self._resume_state.resumed:
            self._run.resumed = True
            if self._resume_state.wandb_runtime is not None:
                self._run.runtime = self._resume_state.wandb_runtime
        self._run.starting_step = self._resume_state.step
        self._run.start_time.FromSeconds(int(start_time))
        self._run.config.CopyFrom(self._interface._make_config(config_dict))
        if self._resume_state.summary is not None:
            self._run.summary.CopyFrom(
                self._interface._make_summary_from_dict(self._resume_state.summary)
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
        if os.getenv("SPELL_RUN_URL"):
            self._sync_spell()

    def _start_run_threads(self, file_dir: str = None) -> None:
        assert self._run  # self._run is configured by caller
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
            file_stream.JsonlFilePolicy(start_chunk_id=self._resume_state.history),
        )
        self._fs.set_file_policy(
            "wandb-events.jsonl",
            file_stream.JsonlFilePolicy(start_chunk_id=self._resume_state.events),
        )
        self._fs.set_file_policy(
            "output.log",
            file_stream.CRDedupeFilePolicy(start_chunk_id=self._resume_state.output),
        )

        # hack to merge run_settings and self._settings object together
        # so that fields like entity or project are available to be attached to Sentry events.
        run_settings = message_to_dict(self._run)
        self._settings = SettingsStatic({**dict(self._settings), **run_settings})
        util.sentry_set_scope(
            settings_dict=self._settings,
        )
        self._fs.start()
        self._pusher = FilePusher(self._api, self._fs, silent=self._settings.silent)
        self._dir_watcher = DirWatcher(
            self._settings, self._api, self._pusher, file_dir
        )
        logger.info(
            "run started: %s with start time %s",
            self._run.run_id,
            self._run.start_time.ToSeconds(),
        )

    def _save_history(self, history_dict: Dict[str, Any]) -> None:
        if self._fs:
            self._fs.push(filenames.HISTORY_FNAME, json.dumps(history_dict))

    def send_history(self, record: "Record") -> None:
        history = record.history
        history_dict = proto_util.dict_from_proto_list(history.item)
        self._save_history(history_dict)

    def send_summary(self, record: "Record") -> None:
        summary_dict = proto_util.dict_from_proto_list(record.summary.update)
        self._cached_summary = summary_dict
        self._update_summary()

    def _update_summary(self) -> None:
        summary_dict = self._cached_summary.copy()
        summary_dict.pop("_wandb", None)
        if self._metadata_summary:
            summary_dict["_wandb"] = self._metadata_summary
        json_summary = json.dumps(summary_dict)
        if self._fs:
            self._fs.push(filenames.SUMMARY_FNAME, json_summary)
        # TODO(jhr): we should only write this at the end of the script
        summary_path = os.path.join(self._settings.files_dir, filenames.SUMMARY_FNAME)
        with open(summary_path, "w") as f:
            f.write(json_summary)
        self._save_file(interface.GlobStr(filenames.SUMMARY_FNAME))

    def send_stats(self, record: "Record") -> None:
        stats = record.stats
        if stats.stats_type != wandb_internal_pb2.StatsRecord.StatsType.SYSTEM:
            return
        if not self._fs:
            return
        if not self._run:
            return
        now = stats.timestamp.seconds
        d = dict()
        for item in stats.item:
            d[item.key] = json.loads(item.value_json)
        row: Dict[str, Any] = dict(system=d)
        self._flatten(row)
        row["_wandb"] = True
        row["_timestamp"] = now
        row["_runtime"] = int(now - self._run.start_time.ToSeconds())
        self._fs.push(filenames.EVENTS_FNAME, json.dumps(row))
        # TODO(jhr): check fs.push results?

    def send_output(self, record: "Record") -> None:
        if not self._fs:
            return
        out = record.output
        prepend = ""
        stream = "stdout"
        if out.output_type == wandb_internal_pb2.OutputRecord.OutputType.STDERR:
            stream = "stderr"
            prepend = "ERROR "
        line = out.line
        if not line.endswith("\n"):
            self._partial_output.setdefault(stream, "")
            if line.startswith("\r"):
                self._partial_output[stream] = ""
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
            line = f"{prepend}{timestamp}{prev_str}{line}"
            self._fs.push(filenames.OUTPUT_FNAME, line)
            self._partial_output[stream] = ""

    def _update_config(self) -> None:
        self._config_needs_debounce = True

    def send_config(self, record: "Record") -> None:
        cfg = record.config
        config_util.update_from_proto(self._consolidated_config, cfg)
        self._update_config()

    def send_metric(self, record: "Record") -> None:
        metric = record.metric
        if metric.glob_name:
            logger.warning("Seen metric with glob (shouldn't happen)")
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

    def send_telemetry(self, record: "Record") -> None:
        telem = record.telemetry
        self._telemetry_obj.MergeFrom(telem)
        self._update_config()

    def _save_file(
        self, fname: interface.GlobStr, policy: "interface.PolicyName" = "end"
    ) -> None:
        logger.info("saving file %s with policy %s", fname, policy)
        if self._dir_watcher:
            self._dir_watcher.update_policy(fname, policy)

    def send_files(self, record: "Record") -> None:
        files = record.files
        for k in files.files:
            # TODO(jhr): fix paths with directories
            self._save_file(
                interface.GlobStr(k.path), interface.file_enum_to_policy(k.policy)
            )

    def send_header(self, record: "Record") -> None:
        pass

    def send_footer(self, record: "Record") -> None:
        pass

    def send_tbrecord(self, record: "Record") -> None:
        # tbrecord watching threads are handled by handler.py
        pass

    def send_link_artifact(self, record: "Record") -> None:
        link = record.link_artifact
        client_id = link.client_id
        server_id = link.server_id
        portfolio_name = link.portfolio_name
        entity = link.portfolio_entity
        project = link.portfolio_project
        aliases = link.portfolio_aliases
        logger.debug(
            f"link_artifact params - client_id={client_id}, server_id={server_id}, pfolio={portfolio_name}, entity={entity}, project={project}"
        )
        if (
            (client_id or server_id)
            and portfolio_name
            and entity
            and project
            and aliases
        ):
            try:
                self._api.link_artifact(
                    client_id, server_id, portfolio_name, entity, project, aliases
                )
            except Exception as e:
                logger.warning("Failed to link artifact to portfolio: %s", e)

    def send_request_log_artifact(self, record: "Record") -> None:
        assert record.control.req_resp
        result = proto_util._result_from_record(record)
        artifact = record.request.log_artifact.artifact
        history_step = record.request.log_artifact.history_step

        try:
            res = self._send_artifact(artifact, history_step)
            assert res, "Unable to send artifact"
            result.response.log_artifact_response.artifact_id = res["id"]
            logger.info(f"logged artifact {artifact.name} - {res}")
        except Exception as e:
            result.response.log_artifact_response.error_message = (
                'error logging artifact "{}/{}": {}'.format(
                    artifact.type, artifact.name, e
                )
            )

        self._respond_result(result)

    def send_request_artifact_send(self, record: "Record") -> None:
        # TODO: combine and eventually remove send_request_log_artifact()

        # for now, we are using req/resp uuid for transaction id
        # in the future this should be part of the message to handle idempotency
        xid = record.uuid

        done_msg = wandb_internal_pb2.ArtifactDoneRequest(xid=xid)
        artifact = record.request.artifact_send.artifact
        try:
            res = self._send_artifact(artifact)
            assert res, "Unable to send artifact"
            done_msg.artifact_id = res["id"]
            logger.info(f"logged artifact {artifact.name} - {res}")
        except Exception as e:
            done_msg.error_message = 'error logging artifact "{}/{}": {}'.format(
                artifact.type, artifact.name, e
            )

        logger.info("send artifact done")
        self._interface._publish_artifact_done(done_msg)

    def send_artifact(self, record: "Record") -> None:
        artifact = record.artifact
        try:
            res = self._send_artifact(artifact)
            logger.info(f"sent artifact {artifact.name} - {res}")
        except Exception as e:
            logger.error(
                'send_artifact: failed for artifact "{}/{}": {}'.format(
                    artifact.type, artifact.name, e
                )
            )

    def _send_artifact(
        self, artifact: "ArtifactRecord", history_step: Optional[int] = None
    ) -> Optional[Dict]:
        assert self._pusher
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
                return None

        metadata = json.loads(artifact.metadata) if artifact.metadata else None
        return saver.save(
            type=artifact.type,
            name=artifact.name,
            client_id=artifact.client_id,
            sequence_client_id=artifact.sequence_client_id,
            metadata=metadata,
            description=artifact.description,
            aliases=artifact.aliases,
            use_after_commit=artifact.use_after_commit,
            distributed_id=artifact.distributed_id,
            finalize=artifact.finalize,
            incremental=artifact.incremental_beta1,
            history_step=history_step,
        )

    def send_alert(self, record: "Record") -> None:
        alert = record.alert
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
                logger.error(f'send_alert: failed for alert "{alert.title}": {e}')

    def finish(self) -> None:
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

    def _max_cli_version(self) -> Optional[str]:
        server_info = self.get_server_info()
        max_cli_version = server_info.get("cliVersionInfo", {}).get(
            "max_cli_version", None
        )
        if not isinstance(max_cli_version, str):
            return None
        return max_cli_version

    def get_viewer_server_info(self) -> None:
        if self._cached_server_info and self._cached_viewer:
            return
        self._cached_viewer, self._cached_server_info = self._api.viewer_server_info()

    def get_viewer_info(self) -> Dict[str, Any]:
        if not self._cached_viewer:
            self.get_viewer_server_info()
        return self._cached_viewer

    def get_server_info(self) -> Dict[str, Any]:
        if not self._cached_server_info:
            self.get_viewer_server_info()
        return self._cached_server_info

    def get_local_info(self) -> "LocalInfo":
        """
        This is a helper function that queries the server to get the local version information.
        First, we perform an introspection, if it returns empty we deduce that the docker image is
        out-of-date. Otherwise, we use the returned values to deduce the state of the local server.
        """
        local_info = wandb_internal_pb2.LocalInfo()

        if self._settings._offline:
            local_info.out_of_date = False
            return local_info

        latest_local_version = "latest"

        # Assuming the query is successful if the result is empty it indicates that
        # the backend is out of date since it doesn't have the desired field
        server_info = self.get_server_info()
        latest_local_version_info = server_info.get("latestLocalVersionInfo", {})
        if latest_local_version_info is None:
            local_info.out_of_date = False
        else:
            local_info.out_of_date = latest_local_version_info.get("outOfDate", True)
            local_info.version = latest_local_version_info.get(
                "latestVersionString", latest_local_version
            )
        return local_info

    def __next__(self) -> "Record":
        return self._record_q.get(block=True)

    next = __next__
