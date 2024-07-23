"""sender."""

import contextlib
import gzip
import json
import logging
import os
import queue
import sys
import threading
import time
import traceback
from collections import defaultdict
from datetime import datetime
from queue import Queue
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Generator,
    List,
    Optional,
    Tuple,
    Type,
    Union,
)

import requests

import wandb
from wandb import util
from wandb.errors import CommError, UsageError
from wandb.errors.util import ProtobufErrorHandler
from wandb.filesync.dir_watcher import DirWatcher
from wandb.proto import wandb_internal_pb2
from wandb.sdk.artifacts.artifact_saver import ArtifactSaver
from wandb.sdk.interface import interface
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal import (
    context,
    datastore,
    file_stream,
    internal_api,
    sender_config,
    update,
)
from wandb.sdk.internal.file_pusher import FilePusher
from wandb.sdk.internal.job_builder import JobBuilder
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.lib import (
    config_util,
    filenames,
    filesystem,
    printer,
    proto_util,
    redirect,
    telemetry,
    tracelog,
)
from wandb.sdk.lib.mailbox import ContextCancelledError
from wandb.sdk.lib.proto_util import message_to_dict

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import (
        ArtifactManifest,
        ArtifactManifestEntry,
        ArtifactRecord,
        HttpResponse,
        LocalInfo,
        Record,
        Result,
        RunExitResult,
        RunRecord,
        SummaryRecord,
    )

    StreamLiterals = Literal["stdout", "stderr"]


logger = logging.getLogger(__name__)


_OUTPUT_MIN_CALLBACK_INTERVAL = 2  # seconds


def _framework_priority() -> Generator[Tuple[str, str], None, None]:
    yield from [
        ("lightgbm", "lightgbm"),
        ("catboost", "catboost"),
        ("xgboost", "xgboost"),
        ("transformers_huggingface", "huggingface"),  # backwards compatibility
        ("transformers", "huggingface"),
        ("pytorch_ignite", "ignite"),  # backwards compatibility
        ("ignite", "ignite"),
        ("pytorch_lightning", "lightning"),
        ("fastai", "fastai"),
        ("torch", "torch"),
        ("keras", "keras"),
        ("tensorflow", "tensorflow"),
        ("sklearn", "sklearn"),
    ]


def _manifest_json_from_proto(manifest: "ArtifactManifest") -> Dict:
    if manifest.version == 1:
        if manifest.manifest_file_path:
            contents = {}
            with gzip.open(manifest.manifest_file_path, "rt") as f:
                for line in f:
                    entry_json = json.loads(line)
                    path = entry_json.pop("path")
                    contents[path] = entry_json
        else:
            contents = {
                content.path: _manifest_entry_from_proto(content)
                for content in manifest.contents
            }
    else:
        raise ValueError(f"unknown artifact manifest version: {manifest.version}")

    return {
        "version": manifest.version,
        "storagePolicy": manifest.storage_policy,
        "storagePolicyConfig": {
            config.key: json.loads(config.value_json)
            for config in manifest.storage_policy_config
        },
        "contents": contents,
    }


def _manifest_entry_from_proto(entry: "ArtifactManifestEntry") -> Dict:
    birth_artifact_id = entry.birth_artifact_id if entry.birth_artifact_id else None
    return {
        "digest": entry.digest,
        "birthArtifactID": birth_artifact_id,
        "ref": entry.ref if entry.ref else None,
        "size": entry.size if entry.size is not None else None,
        "local_path": entry.local_path if entry.local_path else None,
        "skip_cache": entry.skip_cache,
        "extra": {extra.key: json.loads(extra.value_json) for extra in entry.extra},
    }


class ResumeState:
    resumed: bool
    step: int
    history: int
    events: int
    output: int
    runtime: float
    wandb_runtime: Optional[int]
    summary: Optional[Dict[str, Any]]
    config: Optional[Dict[str, Any]]
    tags: Optional[List[str]]

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
        self.tags = None

    def __str__(self) -> str:
        obj = ",".join(map(lambda it: f"{it[0]}={it[1]}", vars(self).items()))
        return f"ResumeState({obj})"


class _OutputRawStream:
    _stopped: threading.Event
    _queue: queue.Queue
    _emulator: redirect.TerminalEmulator
    _writer_thr: threading.Thread
    _reader_thr: threading.Thread

    def __init__(self, stream: str, sm: "SendManager"):
        self._stopped = threading.Event()
        self._queue = queue.Queue()
        self._emulator = redirect.TerminalEmulator()
        self._writer_thr = threading.Thread(
            target=sm._output_raw_writer_thread,
            kwargs=dict(stream=stream),
            daemon=True,
            name=f"OutRawWr-{stream}",
        )
        self._reader_thr = threading.Thread(
            target=sm._output_raw_reader_thread,
            kwargs=dict(stream=stream),
            daemon=True,
            name=f"OutRawRd-{stream}",
        )

    def start(self) -> None:
        self._writer_thr.start()
        self._reader_thr.start()


class SendManager:
    UPDATE_CONFIG_TIME: int = 30
    UPDATE_STATUS_TIME: int = 5

    _settings: SettingsStatic
    _record_q: "Queue[Record]"
    _result_q: "Queue[Result]"
    _interface: InterfaceQueue
    _api_settings: Dict[str, str]
    _partial_output: Dict[str, str]
    _context_keeper: context.ContextKeeper

    _telemetry_obj: telemetry.TelemetryRecord
    _fs: Optional["file_stream.FileStreamApi"]
    _run: Optional["RunRecord"]
    _entity: Optional[str]
    _project: Optional[str]
    _dir_watcher: Optional["DirWatcher"]
    _pusher: Optional["FilePusher"]
    _record_exit: Optional["Record"]
    _exit_result: Optional["RunExitResult"]
    _resume_state: ResumeState
    _rewind_response: Optional[Dict[str, Any]]
    _cached_server_info: Dict[str, Any]
    _cached_viewer: Dict[str, Any]
    _server_messages: List[Dict[str, Any]]
    _ds: Optional[datastore.DataStore]
    _output_raw_streams: Dict["StreamLiterals", _OutputRawStream]
    _output_raw_file: Optional[filesystem.CRDedupedFile]
    _send_record_num: int
    _send_end_offset: int
    _debounce_config_time: float
    _debounce_status_time: float

    def __init__(
        self,
        settings: SettingsStatic,
        record_q: "Queue[Record]",
        result_q: "Queue[Result]",
        interface: InterfaceQueue,
        context_keeper: context.ContextKeeper,
    ) -> None:
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._interface = interface
        self._context_keeper = context_keeper

        self._ds = None
        self._send_record_num = 0
        self._send_end_offset = 0

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
        self._consolidated_config = sender_config.ConfigState()

        self._start_time: int = 0
        self._telemetry_obj = telemetry.TelemetryRecord()
        self._config_metric_pbdict_list: List[Dict[int, Any]] = []
        self._metadata_summary: Dict[str, Any] = defaultdict()
        self._cached_summary: Dict[str, Any] = dict()
        self._config_metric_index_dict: Dict[str, int] = {}
        self._config_metric_dict: Dict[str, wandb_internal_pb2.MetricRecord] = {}
        self._consolidated_summary: Dict[str, Any] = dict()

        self._cached_server_info = dict()
        self._cached_viewer = dict()
        self._server_messages = []

        # State updated by resuming
        self._resume_state = ResumeState()
        self._rewind_response = None

        # State added when run_exit is initiated and complete
        self._record_exit = None
        self._exit_result = None

        self._api = internal_api.Api(
            default_settings=settings, retry_callback=self.retry_callback
        )
        self._api_settings = dict()

        # queue filled by retry_callback
        self._retry_q: Queue[HttpResponse] = queue.Queue()

        # do we need to debounce?
        self._config_needs_debounce: bool = False

        # TODO(jhr): do something better, why do we need to send full lines?
        self._partial_output = dict()

        self._exit_code = 0

        # internal vars for handing raw console output
        self._output_raw_streams = dict()
        self._output_raw_file = None

        # job builder
        self._job_builder = JobBuilder(settings)

        time_now = time.monotonic()
        self._debounce_config_time = time_now
        self._debounce_status_time = time_now

    @classmethod
    def setup(
        cls,
        root_dir: str,
        resume: Union[None, bool, str],
    ) -> "SendManager":
        """Set up a standalone SendManager.

        Currently, we're using this primarily for `sync.py`.
        """
        files_dir = os.path.join(root_dir, "files")
        settings = wandb.Settings(
            files_dir=files_dir,
            root_dir=root_dir,
            # _start_time=0,
            resume=resume,
            # ignore_globs=(),
            _sync=True,
            disable_job_creation=False,
            _file_stream_timeout_seconds=0,
        )
        record_q: Queue[Record] = queue.Queue()
        result_q: Queue[Result] = queue.Queue()
        publish_interface = InterfaceQueue(record_q=record_q)
        context_keeper = context.ContextKeeper()
        return SendManager(
            settings=SettingsStatic(settings.to_proto()),
            record_q=record_q,
            result_q=result_q,
            interface=publish_interface,
            context_keeper=context_keeper,
        )

    def __len__(self) -> int:
        return self._record_q.qsize()

    def __enter__(self) -> "SendManager":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        exc_traceback: Optional[traceback.TracebackException],
    ) -> Literal[False]:
        while self:
            data = next(self)
            self.send(data)
        self.finish()
        return False

    def retry_callback(self, status: int, response_text: str) -> None:
        response = wandb_internal_pb2.HttpResponse()
        response.http_status_code = status
        response.http_response_text = response_text
        self._retry_q.put(response)

    def send(self, record: "Record") -> None:
        self._update_record_num(record.num)
        self._update_end_offset(record.control.end_offset)

        record_type = record.WhichOneof("record_type")
        assert record_type
        handler_str = "send_" + record_type
        send_handler = getattr(self, handler_str, None)
        # Don't log output to reduce log noise
        if record_type not in {"output", "request", "output_raw"}:
            logger.debug(f"send: {record_type}")
        assert send_handler, f"unknown send handler: {handler_str}"

        context_id = context.context_id_from_record(record)
        api_context = self._context_keeper.get(context_id)
        try:
            self._api.set_local_context(api_context)
            send_handler(record)
        except ContextCancelledError:
            logger.debug(f"Record cancelled: {record_type}")
            self._context_keeper.release(context_id)
        finally:
            self._api.clear_local_context()

    def send_preempting(self, _: "Record") -> None:
        if self._fs:
            self._fs.enqueue_preempting()

    def send_request_sender_mark(self, _: "Record") -> None:
        self._maybe_report_status(always=True)

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
        context_id = context.context_id_from_result(result)
        self._context_keeper.release(context_id)
        self._result_q.put(result)

    def _flatten(self, dictionary: Dict) -> None:
        if isinstance(dictionary, dict):
            for k, v in list(dictionary.items()):
                if isinstance(v, dict):
                    self._flatten(v)
                    dictionary.pop(k)
                    for k2, v2 in v.items():
                        dictionary[k + "." + k2] = v2

    def _update_record_num(self, record_num: int) -> None:
        if not record_num:
            return
        # Currently how we handle offline mode and syncing is not
        # compatible with this assertion due to how the exit record
        # is (mis)handled:
        #   - using "always_send" in offline mode to trigger defer
        #     state machine
        #   - skipping the exit record in `wandb sync` mode so that
        #     it is always executed as the last record
        if not self._settings._offline and not self._settings._sync:
            assert record_num == self._send_record_num + 1
        self._send_record_num = record_num

    def _update_end_offset(self, end_offset: int) -> None:
        if not end_offset:
            return
        self._send_end_offset = end_offset

    def send_request_sender_read(self, record: "Record") -> None:
        if self._ds is None:
            self._ds = datastore.DataStore()
            self._ds.open_for_scan(self._settings.sync_file)

        # TODO(cancel_paused): implement cancel_set logic
        # The idea is that there is an active request to cancel a
        # message that is being read from the transaction log below

        start_offset = record.request.sender_read.start_offset
        final_offset = record.request.sender_read.final_offset
        self._ds.seek(start_offset)

        current_end_offset = 0
        while current_end_offset < final_offset:
            data = self._ds.scan_data()
            assert data
            current_end_offset = self._ds.get_offset()

            send_record = wandb_internal_pb2.Record()
            send_record.ParseFromString(data)
            self._update_end_offset(current_end_offset)
            self.send(send_record)

            # make sure we perform deferred operations
            self.debounce()

        # make sure that we always update writer for every sended read request
        self._maybe_report_status(always=True)

    def send_request_check_version(self, record: "Record") -> None:
        assert record.control.req_resp or record.control.mailbox_slot
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

    def send_request_stop_status(self, record: "Record") -> None:
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

    def _maybe_update_config(self, always: bool = False) -> None:
        time_now = time.monotonic()
        if (
            not always
            and time_now < self._debounce_config_time + self.UPDATE_CONFIG_TIME
        ):
            return
        if self._config_needs_debounce:
            self._debounce_config()
        self._debounce_config_time = time_now

    def _maybe_report_status(self, always: bool = False) -> None:
        time_now = time.monotonic()
        if (
            not always
            and time_now < self._debounce_status_time + self.UPDATE_STATUS_TIME
        ):
            return
        self._debounce_status_time = time_now

        status_report = wandb_internal_pb2.StatusReportRequest(
            record_num=self._send_record_num,
            sent_offset=self._send_end_offset,
        )
        status_time = time.time()
        status_report.sync_time.FromMicroseconds(int(status_time * 1e6))
        record = self._interface._make_request(status_report=status_report)
        self._interface._publish(record)

    def debounce(self, final: bool = False) -> None:
        self._maybe_report_status(always=final)
        self._maybe_update_config(always=final)

    def _debounce_config(self) -> None:
        config_value_dict = self._config_backend_dict()
        # TODO(jhr): check result of upsert_run?
        if self._run:
            self._api.upsert_run(
                name=self._run.run_id,
                config=config_value_dict,
                **self._api_settings,  # type: ignore
            )
        self._config_save(config_value_dict)
        self._config_needs_debounce = False

    def send_request_network_status(self, record: "Record") -> None:
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
        # track where the exit came from
        self._record_exit = record

        run_exit = record.exit
        self._exit_code = run_exit.exit_code
        logger.info("handling exit code: %s", run_exit.exit_code)
        runtime = run_exit.runtime
        logger.info("handling runtime: %s", run_exit.runtime)
        self._metadata_summary["runtime"] = runtime
        self._update_summary()

        # We need to give the request queue a chance to empty between states
        # so use handle_request_defer as a state machine.
        logger.info("send defer")
        self._interface.publish_defer()

    def send_final(self, record: "Record") -> None:
        pass

    def _flush_run(self) -> None:
        pass

    def send_request_status_report(self, record: "Record") -> None:
        # todo? this is just a noop to please wandb sync
        pass

    def send_request_defer(self, record: "Record") -> None:  # noqa: C901
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
        elif state == defer.FLUSH_RUN:
            self._flush_run()
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
            self.debounce(final=True)
            transition_state()
        elif state == defer.FLUSH_OUTPUT:
            self._output_raw_finish()
            transition_state()
        elif state == defer.FLUSH_JOB:
            self._flush_job()
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
        elif state == defer.JOIN_FP:
            if self._pusher:
                self._pusher.join()
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

        # Report response to mailbox
        if self._record_exit and self._record_exit.control.mailbox_slot:
            result = proto_util._result_from_record(self._record_exit)
            result.exit_result.CopyFrom(exit_result)
            self._respond_result(result)

    def send_request_poll_exit(self, record: "Record") -> None:
        if not record.control.req_resp and not record.control.mailbox_slot:
            return

        result = proto_util._result_from_record(record)

        if self._pusher:
            _alive, status = self._pusher.get_status()
            file_counts = self._pusher.file_counts_by_category()
            resp = result.response.poll_exit_response
            resp.pusher_stats.uploaded_bytes = status.uploaded_bytes
            resp.pusher_stats.total_bytes = status.total_bytes
            resp.pusher_stats.deduped_bytes = status.deduped_bytes
            resp.file_counts.wandb_count = file_counts.wandb
            resp.file_counts.media_count = file_counts.media
            resp.file_counts.artifact_count = file_counts.artifact
            resp.file_counts.other_count = file_counts.other

        if self._exit_result:
            result.response.poll_exit_response.done = True
            result.response.poll_exit_response.exit_result.CopyFrom(self._exit_result)

        self._respond_result(result)

    def send_request_server_info(self, record: "Record") -> None:
        assert record.control.req_resp or record.control.mailbox_slot
        result = proto_util._result_from_record(record)

        result.response.server_info_response.local_info.CopyFrom(self.get_local_info())
        for message in self._server_messages:
            # guard against the case the message level returns malformed from server
            message_level = str(message.get("messageLevel"))
            message_level_sanitized = int(
                printer.INFO if not message_level.isdigit() else message_level
            )
            result.response.server_info_response.server_messages.item.append(
                wandb_internal_pb2.ServerMessage(
                    utf_text=message.get("utfText", ""),
                    plain_text=message.get("plainText", ""),
                    html_text=message.get("htmlText", ""),
                    type=message.get("messageType", ""),
                    level=message_level_sanitized,
                )
            )
        self._respond_result(result)

    def _setup_resume(
        self, run: "RunRecord"
    ) -> Optional["wandb_internal_pb2.ErrorInfo"]:
        """Queries the backend for a run; fail if the settings are incompatible."""
        if not self._settings.resume:
            return None

        # TODO: This causes a race, we need to make the upsert atomically
        # only create or update depending on the resume config
        # we use the runs entity if set, otherwise fallback to users entity
        # todo: ensure entity is not None as self._entity is Optional[str]
        entity = run.entity or self._entity
        logger.info(
            "checking resume status for %s/%s/%s", entity, run.project, run.run_id
        )
        resume_status = self._api.run_resume_status(
            entity=entity,  # type: ignore
            project_name=run.project,
            name=run.run_id,
        )
        # No resume status = run does not exist; No t key in wandbConfig = run exists but hasn't been inited
        if not resume_status or '"t":' not in resume_status.get("wandbConfig", ""):
            if self._settings.resume == "must":
                error = wandb_internal_pb2.ErrorInfo()
                error.code = wandb_internal_pb2.ErrorInfo.ErrorCode.USAGE
                error.message = (
                    "You provided an invalid value for the `resume` argument."
                    f" The value 'must' is not a valid option for resuming a run ({run.run_id}) that has not been initialized."
                    " Please check your inputs and try again with a valid run ID."
                    " If you are trying to start a new run, please omit the `resume` argument or use `resume='allow'`."
                )
                return error
            return None

        #
        # handle cases where we have resume_status
        #
        if self._settings.resume == "never":
            error = wandb_internal_pb2.ErrorInfo()
            error.code = wandb_internal_pb2.ErrorInfo.ErrorCode.USAGE
            error.message = (
                "You provided an invalid value for the `resume` argument."
                f" The value 'never' is not a valid option for resuming a run ({run.run_id}) that already exists."
                " Please check your inputs and try again with a valid value for the `resume` argument."
            )
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
            tags = resume_status.get("tags") or []

        except (IndexError, ValueError) as e:
            logger.error("unable to load resume tails", exc_info=e)
            if self._settings.resume == "must":
                error = wandb_internal_pb2.ErrorInfo()
                error.code = wandb_internal_pb2.ErrorInfo.ErrorCode.USAGE
                error.message = "resume='must' but could not resume ({}) ".format(
                    run.run_id
                )
                return error

        # TODO: Do we need to restore config / summary?
        # System metrics runtime is usually greater than history
        self._resume_state.runtime = max(events_rt, history_rt)
        last_step = history.get("_step", 0)
        history_line_count = resume_status["historyLineCount"]
        self._resume_state.step = last_step + 1 if history_line_count > 0 else last_step
        self._resume_state.history = history_line_count
        self._resume_state.events = resume_status["eventsLineCount"]
        self._resume_state.output = resume_status["logLineCount"]
        self._resume_state.config = config
        self._resume_state.summary = summary
        self._resume_state.tags = tags
        self._resume_state.resumed = True
        logger.info("configured resuming with: {}".format(self._resume_state))
        return None

    def _telemetry_get_framework(self) -> str:
        """Get telemetry data for internal config structure."""
        # detect framework by checking what is loaded
        imports: telemetry.TelemetryImports
        if self._telemetry_obj.HasField("imports_finish"):
            imports = self._telemetry_obj.imports_finish
        elif self._telemetry_obj.HasField("imports_init"):
            imports = self._telemetry_obj.imports_init
        else:
            return ""
        framework = next(
            (n for f, n in _framework_priority() if getattr(imports, f, False)), ""
        )
        return framework

    def _config_backend_dict(self) -> sender_config.BackendConfigDict:
        config = self._consolidated_config or sender_config.ConfigState()

        return config.to_backend_dict(
            telemetry_record=self._telemetry_obj,
            framework=self._telemetry_get_framework(),
            start_time_millis=self._start_time,
            metric_pbdicts=self._config_metric_pbdict_list,
        )

    def _config_save(
        self,
        config_value_dict: sender_config.BackendConfigDict,
    ) -> None:
        config_path = os.path.join(self._settings.files_dir, "config.yaml")
        config_util.save_config_file_from_dict(config_path, config_value_dict)

    def _sync_spell(self) -> None:
        """Sync this run with spell."""
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

    def _setup_fork(self, server_run: dict):
        assert self._settings.fork_from
        assert self._settings.fork_from.metric == "_step"
        assert self._run
        first_step = int(self._settings.fork_from.value) + 1
        self._resume_state.step = first_step
        self._resume_state.history = server_run.get("historyLineCount", 0)
        self._run.forked = True
        self._run.starting_step = first_step

    def _load_rewind_state(self, run: "RunRecord"):
        assert self._settings.resume_from
        self._rewind_response = self._api.rewind_run(
            run_name=run.run_id,
            entity=run.entity or None,
            project=run.project or None,
            metric_name=self._settings.resume_from.metric,
            metric_value=self._settings.resume_from.value,
            program_path=self._settings.program or None,
        )
        self._resume_state.history = self._rewind_response.get("historyLineCount", 0)
        self._resume_state.config = json.loads(
            self._rewind_response.get("config", "{}")
        )

    def _install_rewind_state(self):
        assert self._settings.resume_from
        assert self._settings.resume_from.metric == "_step"
        assert self._run
        assert self._rewind_response

        first_step = int(self._settings.resume_from.value) + 1
        self._resume_state.step = first_step

        # We set the fork flag here because rewind uses the forking
        # infrastructure under the hood. Setting `forked` here
        # ensures that run._step is properly set in the user process.
        self._run.forked = True
        self._run.starting_step = first_step

    def _handle_error(
        self,
        record: "Record",
        error: "wandb_internal_pb2.ErrorInfo",
        run: "RunRecord",
    ) -> None:
        if record.control.req_resp or record.control.mailbox_slot:
            result = proto_util._result_from_record(record)
            result.run_result.run.CopyFrom(run)
            result.run_result.error.CopyFrom(error)
            self._respond_result(result)
        else:
            logger.error("Got error in async mode: %s", error.message)

    def send_run(self, record: "Record", file_dir: Optional[str] = None) -> None:
        run = record.run
        error = None
        is_wandb_init = self._run is None

        # save start time of a run
        self._start_time = int(run.start_time.ToMicroseconds() // 1e6)

        # update telemetry
        if run.telemetry:
            self._telemetry_obj.MergeFrom(run.telemetry)
        if self._settings._sync:
            self._telemetry_obj.feature.sync = True

        # build config dict
        config_value_dict: Optional[sender_config.BackendConfigDict] = None
        if run.config:
            self._consolidated_config.update_from_proto(run.config)
            config_value_dict = self._config_backend_dict()
            self._config_save(config_value_dict)

        do_fork = self._settings.fork_from is not None and is_wandb_init
        do_rewind = self._settings.resume_from is not None and is_wandb_init
        do_resume = bool(self._settings.resume)

        num_resume_options_set = sum([do_fork, do_rewind, do_resume])
        if num_resume_options_set > 1:
            error = wandb_internal_pb2.ErrorInfo()
            error.code = wandb_internal_pb2.ErrorInfo.ErrorCode.USAGE
            error.message = (
                "Multiple resume options specified. "
                "Please specify only one of `fork_from`, `resume`, or `resume_from`."
            )
            self._handle_error(record, error, run)

        if is_wandb_init:
            # Ensure we have a project to query for status
            if run.project == "":
                run.project = util.auto_project_name(self._settings.program)
            # Only check resume status on `wandb.init`

            if do_resume:
                error = self._setup_resume(run)

            elif do_rewind:
                error = self._load_rewind_state(run)

        if error is not None:
            self._handle_error(record, error, run)
            return

        # Save the resumed config
        if self._resume_state.config is not None:
            self._consolidated_config.merge_resumed_config(
                config_util.dict_strip_value_dict(self._resume_state.config)
            )

            config_value_dict = self._config_backend_dict()
            self._config_save(config_value_dict)

        # handle empty config
        # TODO(jhr): consolidate the 4 ways config is built:
        #            (passed config, empty config, resume config, send_config)
        if not config_value_dict:
            config_value_dict = self._config_backend_dict()
            self._config_save(config_value_dict)

        try:
            server_run = self._init_run(run, config_value_dict)
        except (CommError, UsageError) as e:
            logger.error(e, exc_info=True)
            error = ProtobufErrorHandler.from_exception(e)
            self._handle_error(record, error, run)
            return

        assert self._run  # self._run is configured in _init_run()

        if do_fork:
            error = self._setup_fork(server_run)

        if error is not None:
            self._handle_error(record, error, run)
            return

        if record.control.req_resp or record.control.mailbox_slot:
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

    def _update_resume_state(self, is_rewinding: bool, inserted: bool):
        assert self._run
        if self._resume_state.resumed:
            self._run.resumed = True
            if self._resume_state.wandb_runtime is not None:
                self._run.runtime = self._resume_state.wandb_runtime
        elif is_rewinding:
            # because is_rewinding is mutually exclusive with self._resume_state.resumed,
            # this block will always execute if is_rewinding is set
            self._install_rewind_state()
        else:
            # If the user is not resuming, and we didn't insert on upsert_run then
            # it is likely that we are overwriting the run which we might want to
            # prevent in the future.  This could be a false signal since an upsert_run
            # message which gets retried in the network could also show up as not
            # inserted.
            if not inserted:
                # no need to flush this, it will get updated eventually
                self._telemetry_obj.feature.maybe_run_overwrite = True

    def _init_run(
        self,
        run: "RunRecord",
        config_dict: Optional[sender_config.BackendConfigDict],
    ) -> dict:
        # We subtract the previous runs runtime when resuming
        start_time = (
            run.start_time.ToMicroseconds() / 1e6
        ) - self._resume_state.runtime
        # TODO: we don't check inserted currently, ultimately we should make
        # the upsert know the resume state and fail transactionally

        if self._resume_state and self._resume_state.tags and not run.tags:
            run.tags.extend(self._resume_state.tags)

        is_rewinding = bool(self._settings.resume_from)
        if is_rewinding:
            assert self._rewind_response
            server_run = self._rewind_response
            server_messages = None
            inserted = True
        else:
            server_run, inserted, server_messages = self._api.upsert_run(
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
                commit=run.git.commit or None,
            )

        # TODO: we don't want to create jobs in sweeps, since the
        #  executable doesn't appear to be consistent
        if run.sweep_id:
            self._job_builder.disable = True

        self._server_messages = server_messages or []
        self._run = run

        if self._resume_state.resumed and is_rewinding:
            # this should not ever be possible to hit, since we check for
            # resumption above and raise an error if resumption is specified
            # twice.
            raise ValueError(
                "Cannot attempt to rewind and resume a run - only one of "
                "`resume` or `resume_from` can be specified."
            )

        self._update_resume_state(is_rewinding, inserted)
        self._run.starting_step = self._resume_state.step
        self._run.start_time.FromMicroseconds(int(start_time * 1e6))
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
        return server_run

    def _start_run_threads(self, file_dir: Optional[str] = None) -> None:
        assert self._run  # self._run is configured by caller
        self._fs = file_stream.FileStreamApi(
            self._api,
            self._run.run_id,
            self._run.start_time.ToMicroseconds() / 1e6,
            timeout=self._settings._file_stream_timeout_seconds,
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
        _settings = dict(self._settings)
        _settings.update(run_settings)
        wandb._sentry.configure_scope(tags=_settings, process_context="internal")

        self._fs.start()
        self._pusher = FilePusher(self._api, self._fs, settings=self._settings)
        self._dir_watcher = DirWatcher(self._settings, self._pusher, file_dir)
        logger.info(
            "run started: %s with start time %s",
            self._run.run_id,
            self._run.start_time.ToMicroseconds() / 1e6,
        )

    def _save_history(self, history_dict: Dict[str, Any]) -> None:
        if self._fs:
            self._fs.push(filenames.HISTORY_FNAME, json.dumps(history_dict))

    def send_history(self, record: "Record") -> None:
        history = record.history
        history_dict = proto_util.dict_from_proto_list(history.item)
        self._save_history(history_dict)

    def _update_summary_record(self, summary: "SummaryRecord") -> None:
        summary_dict = proto_util.dict_from_proto_list(summary.update)
        self._cached_summary = summary_dict
        self._update_summary()

    def send_summary(self, record: "Record") -> None:
        self._update_summary_record(record.summary)

    def send_request_summary_record(self, record: "Record") -> None:
        self._update_summary_record(record.request.summary_record.summary)

    def _update_summary(self) -> None:
        summary_dict = self._cached_summary.copy()
        summary_dict.pop("_wandb", None)
        if self._metadata_summary:
            summary_dict["_wandb"] = self._metadata_summary
        # merge with consolidated summary
        self._consolidated_summary.update(summary_dict)
        json_summary = json.dumps(self._consolidated_summary)
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
        now_us = stats.timestamp.ToMicroseconds()
        start_us = self._run.start_time.ToMicroseconds()
        d = dict()
        for item in stats.item:
            d[item.key] = json.loads(item.value_json)
        row: Dict[str, Any] = dict(system=d)
        self._flatten(row)
        row["_wandb"] = True
        row["_timestamp"] = now_us / 1e6
        row["_runtime"] = (now_us - start_us) / 1e6
        self._fs.push(filenames.EVENTS_FNAME, json.dumps(row))
        # TODO(jhr): check fs.push results?

    def _output_raw_finish(self) -> None:
        for stream, output_raw in self._output_raw_streams.items():
            output_raw._stopped.set()

            # shut down threads
            output_raw._writer_thr.join(timeout=5)
            if output_raw._writer_thr.is_alive():
                logger.info("processing output...")
                output_raw._writer_thr.join()
            output_raw._reader_thr.join()

            # flush output buffers and files
            self._output_raw_flush(stream)
        self._output_raw_streams = {}
        if self._output_raw_file:
            self._output_raw_file.close()
            self._output_raw_file = None

    def _output_raw_writer_thread(self, stream: "StreamLiterals") -> None:
        while True:
            output_raw = self._output_raw_streams[stream]
            if output_raw._queue.empty():
                if output_raw._stopped.is_set():
                    return
                time.sleep(0.5)
                continue
            data = []
            while not output_raw._queue.empty():
                data.append(output_raw._queue.get())
            if output_raw._stopped.is_set() and sum(map(len, data)) > 100000:
                logger.warning("Terminal output too large. Logging without processing.")
                self._output_raw_flush(stream)
                for line in data:
                    self._output_raw_flush(stream, line)
                # TODO: lets mark that this happened in telemetry
                return
            try:
                output_raw._emulator.write("".join(data))
            except Exception as e:
                logger.warning(f"problem writing to output_raw emulator: {e}")

    def _output_raw_reader_thread(self, stream: "StreamLiterals") -> None:
        output_raw = self._output_raw_streams[stream]
        while not (output_raw._stopped.is_set() and output_raw._queue.empty()):
            self._output_raw_flush(stream)
            time.sleep(_OUTPUT_MIN_CALLBACK_INTERVAL)

    def _output_raw_flush(
        self, stream: "StreamLiterals", data: Optional[str] = None
    ) -> None:
        if data is None:
            output_raw = self._output_raw_streams[stream]
            try:
                data = output_raw._emulator.read()
            except Exception as e:
                logger.warning(f"problem reading from output_raw emulator: {e}")
        if data:
            self._send_output_line(stream, data)
            if self._output_raw_file:
                self._output_raw_file.write(data.encode("utf-8"))

    def send_request_python_packages(self, record: "Record") -> None:
        import os

        from wandb.sdk.lib.filenames import REQUIREMENTS_FNAME

        installed_packages_list = sorted(
            f"{r.name}=={r.version}" for r in record.request.python_packages.package
        )
        with open(os.path.join(self._settings.files_dir, REQUIREMENTS_FNAME), "w") as f:
            f.write("\n".join(installed_packages_list))

    def send_output(self, record: "Record") -> None:
        if not self._fs:
            return
        out = record.output
        stream: StreamLiterals = "stdout"
        if out.output_type == wandb_internal_pb2.OutputRecord.OutputType.STDERR:
            stream = "stderr"
        line = out.line
        self._send_output_line(stream, line)

    def send_output_raw(self, record: "Record") -> None:
        if not self._fs:
            return
        out = record.output_raw
        stream: StreamLiterals = "stdout"
        if out.output_type == wandb_internal_pb2.OutputRawRecord.OutputType.STDERR:
            stream = "stderr"
        line = out.line

        output_raw = self._output_raw_streams.get(stream)
        if not output_raw:
            output_raw = _OutputRawStream(stream=stream, sm=self)
            self._output_raw_streams[stream] = output_raw

            # open the console output file shared between both streams
            if not self._output_raw_file:
                output_log_path = os.path.join(
                    self._settings.files_dir, filenames.OUTPUT_FNAME
                )
                output_raw_file = None
                try:
                    output_raw_file = filesystem.CRDedupedFile(
                        open(output_log_path, "wb")
                    )
                except OSError as e:
                    logger.warning(f"could not open output_raw_file: {e}")
                if output_raw_file:
                    self._output_raw_file = output_raw_file
            output_raw.start()

        output_raw._queue.put(line)

    def _send_output_line(self, stream: "StreamLiterals", line: str) -> None:
        """Combined writer for raw and non raw output lines.

        This is combined because they are both post emulator.
        """
        prepend = ""
        if stream == "stderr":
            prepend = "ERROR "
        if not line.endswith("\n"):
            self._partial_output.setdefault(stream, "")
            if line.startswith("\r"):
                # TODO: maybe we shouldnt just drop this, what if there was some \ns in the partial
                # that should probably be the check instead of not line.endswith(\n")
                # logger.info(f"Dropping data {self._partial_output[stream]}")
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
            if self._fs:
                self._fs.push(filenames.OUTPUT_FNAME, line)
            self._partial_output[stream] = ""

    def _update_config(self) -> None:
        self._config_needs_debounce = True

    def send_config(self, record: "Record") -> None:
        self._consolidated_config.update_from_proto(record.config)
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

    def _update_telemetry_record(self, telemetry: telemetry.TelemetryRecord) -> None:
        self._telemetry_obj.MergeFrom(telemetry)
        self._update_config()

    def send_telemetry(self, record: "Record") -> None:
        self._update_telemetry_record(record.telemetry)

    def send_request_telemetry_record(self, record: "Record") -> None:
        self._update_telemetry_record(record.request.telemetry_record.telemetry)

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

    def send_request_link_artifact(self, record: "Record") -> None:
        if not (record.control.req_resp or record.control.mailbox_slot):
            raise ValueError(
                f"Expected either `req_resp` or `mailbox_slot`, got: {record.control!r}"
            )
        result = proto_util._result_from_record(record)
        link = record.request.link_artifact
        client_id = link.client_id
        server_id = link.server_id
        portfolio_name = link.portfolio_name
        entity = link.portfolio_entity
        project = link.portfolio_project
        aliases = link.portfolio_aliases
        logger.debug(
            f"link_artifact params - client_id={client_id}, server_id={server_id}, pfolio={portfolio_name}, entity={entity}, project={project}"
        )
        if (client_id or server_id) and portfolio_name and entity and project:
            try:
                self._api.link_artifact(
                    client_id, server_id, portfolio_name, entity, project, aliases
                )
            except Exception as e:
                result.response.log_artifact_response.error_message = f'error linking artifact to "{entity}/{project}/{portfolio_name}"; error: {e}'
                logger.warning("Failed to link artifact to portfolio: %s", e)
        self._respond_result(result)

    def send_use_artifact(self, record: "Record") -> None:
        """Pretend to send a used artifact.

        This function doesn't actually send anything, it is just used internally.
        """
        use = record.use_artifact

        if use.type == "job" and not use.partial.job_name:
            self._job_builder.disable = True
        elif use.partial.job_name:
            # job is partial, let job builder rebuild job, set job source dict
            self._job_builder.set_partial_source_id(use.id)

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
                f'error logging artifact "{artifact.type}/{artifact.name}": {e}'
            )

        self._respond_result(result)

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
        from wandb.util import parse_version

        assert self._pusher
        saver = ArtifactSaver(
            api=self._api,
            digest=artifact.digest,
            manifest_json=_manifest_json_from_proto(artifact.manifest),
            file_pusher=self._pusher,
            is_user_created=artifact.user_created,
        )

        if artifact.distributed_id:
            max_cli_version = self._max_cli_version()
            if max_cli_version is None or parse_version(
                max_cli_version
            ) < parse_version("0.10.16"):
                logger.warning(
                    "This W&B Server doesn't support distributed artifacts, "
                    "have your administrator install wandb/local >= 0.9.37"
                )
                return None

        metadata = json.loads(artifact.metadata) if artifact.metadata else None
        res = saver.save(
            type=artifact.type,
            name=artifact.name,
            client_id=artifact.client_id,
            sequence_client_id=artifact.sequence_client_id,
            metadata=metadata,
            ttl_duration_seconds=artifact.ttl_duration_seconds or None,
            description=artifact.description or None,
            aliases=artifact.aliases,
            use_after_commit=artifact.use_after_commit,
            distributed_id=artifact.distributed_id,
            finalize=artifact.finalize,
            incremental=artifact.incremental_beta1,
            history_step=history_step,
            base_id=artifact.base_id or None,
        )

        self._job_builder._handle_server_artifact(res, artifact)

        if artifact.manifest.manifest_file_path:
            with contextlib.suppress(FileNotFoundError):
                os.remove(artifact.manifest.manifest_file_path)
        return res

    def send_alert(self, record: "Record") -> None:
        from wandb.util import parse_version

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
                logger.error(f"send_alert: failed for alert {alert.title!r}: {e}")

    def finish(self) -> None:
        logger.info("shutting down sender")
        # if self._tb_watcher:
        #     self._tb_watcher.finish()
        self._output_raw_finish()
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
        wandb._sentry.end_session()

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
        """Queries the server to get the local version information.

        First, we perform an introspection, if it returns empty we deduce that the
        docker image is out-of-date. Otherwise, we use the returned values to deduce the
        state of the local server.
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

    def _flush_job(self) -> None:
        if self._job_builder.disable or self._settings._offline:
            return
        self._job_builder.set_config(self._consolidated_config.non_internal_config())
        summary_dict = self._cached_summary.copy()
        summary_dict.pop("_wandb", None)
        self._job_builder.set_summary(summary_dict)

        artifact = self._job_builder.build(api=self._api)
        if artifact is not None and self._run is not None:
            proto_artifact = self._interface._make_artifact(artifact)
            proto_artifact.run_id = self._run.run_id
            proto_artifact.project = self._run.project
            proto_artifact.entity = self._run.entity
            # TODO: this should be removed when the latest tag is handled
            # by the backend (WB-12116)
            proto_artifact.aliases.append("latest")
            # add docker image tag
            for alias in self._job_builder._aliases:
                proto_artifact.aliases.append(alias)

            proto_artifact.user_created = True
            proto_artifact.use_after_commit = True
            proto_artifact.finalize = True

            self._interface._publish_artifact(proto_artifact)

    def __next__(self) -> "Record":
        return self._record_q.get(block=True)

    next = __next__
