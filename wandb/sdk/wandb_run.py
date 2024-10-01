import _thread as thread
import atexit
import functools
import glob
import json
import logging
import numbers
import os
import pathlib
import re
import sys
import threading
import time
import traceback
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    NamedTuple,
    Optional,
    Sequence,
    TextIO,
    Tuple,
    Type,
    Union,
)

import requests

import wandb
import wandb.env
from wandb import errors, trigger
from wandb._globals import _datatypes_set_callback
from wandb.apis import internal, public
from wandb.apis.internal import Api
from wandb.apis.public import Api as PublicApi
from wandb.errors import CommError
from wandb.integration.torch import wandb_torch
from wandb.plot.viz import CustomChart, Visualize, custom_chart
from wandb.proto.wandb_internal_pb2 import (
    MetricRecord,
    PollExitResponse,
    Result,
    RunRecord,
)
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.internal import job_builder
from wandb.sdk.lib.import_hooks import (
    register_post_import_hook,
    unregister_post_import_hook,
)
from wandb.sdk.lib.paths import FilePathStr, LogicalPath, StrPath
from wandb.util import (
    _is_artifact_object,
    _is_artifact_string,
    _is_artifact_version_weave_dict,
    _is_py_requirements_or_dockerfile,
    _resolve_aliases,
    add_import_hook,
    parse_artifact_string,
)

from . import wandb_config, wandb_metric, wandb_summary
from .artifacts._validators import validate_aliases, validate_tags
from .data_types._dtypes import TypeRegistry
from .interface.interface import FilesDict, GlobStr, InterfaceBase, PolicyName
from .interface.summary_record import SummaryRecord
from .lib import (
    config_util,
    deprecate,
    filenames,
    filesystem,
    ipython,
    module,
    proto_util,
    redirect,
    telemetry,
)
from .lib.exit_hooks import ExitHooks
from .lib.gitlib import GitRepo
from .lib.mailbox import MailboxError, MailboxHandle, MailboxProbe, MailboxProgress
from .lib.printer import get_printer
from .lib.proto_util import message_to_dict
from .lib.reporting import Reporter
from .lib.wburls import wburls
from .wandb_alerts import AlertLevel
from .wandb_settings import Settings
from .wandb_setup import _WandbSetup

if TYPE_CHECKING:
    if sys.version_info >= (3, 8):
        from typing import TypedDict
    else:
        from typing_extensions import TypedDict

    import wandb.apis.public
    import wandb.sdk.backend.backend
    import wandb.sdk.interface.interface_queue
    from wandb.proto.wandb_internal_pb2 import (
        GetSummaryResponse,
        InternalMessagesResponse,
        SampledHistoryResponse,
    )

    from .lib.printer import PrinterJupyter, PrinterTerm

    class GitSourceDict(TypedDict):
        remote: str
        commit: str
        entrypoint: List[str]
        args: Sequence[str]

    class ArtifactSourceDict(TypedDict):
        artifact: str
        entrypoint: List[str]
        args: Sequence[str]

    class ImageSourceDict(TypedDict):
        image: str
        args: Sequence[str]

    class JobSourceDict(TypedDict, total=False):
        _version: str
        source_type: str
        source: Union[GitSourceDict, ArtifactSourceDict, ImageSourceDict]
        input_types: Dict[str, Any]
        output_types: Dict[str, Any]
        runtime: Optional[str]


logger = logging.getLogger("wandb")
EXIT_TIMEOUT = 60
RE_LABEL = re.compile(r"[a-zA-Z0-9_-]+$")


class TeardownStage(IntEnum):
    EARLY = 1
    LATE = 2


class TeardownHook(NamedTuple):
    call: Callable[[], None]
    stage: TeardownStage


class RunStatusChecker:
    """Periodically polls the background process for relevant updates.

    - check if the user has requested a stop.
    - check the network status.
    - check the run sync status.
    """

    _stop_status_lock: threading.Lock
    _stop_status_handle: Optional[MailboxHandle]
    _network_status_lock: threading.Lock
    _network_status_handle: Optional[MailboxHandle]
    _internal_messages_lock: threading.Lock
    _internal_messages_handle: Optional[MailboxHandle]

    def __init__(
        self,
        interface: InterfaceBase,
        stop_polling_interval: int = 15,
        retry_polling_interval: int = 5,
        internal_messages_polling_interval: int = 10,
    ) -> None:
        self._interface = interface
        self._stop_polling_interval = stop_polling_interval
        self._retry_polling_interval = retry_polling_interval
        self._internal_messages_polling_interval = internal_messages_polling_interval

        self._join_event = threading.Event()

        self._stop_status_lock = threading.Lock()
        self._stop_status_handle = None
        self._stop_thread = threading.Thread(
            target=self.check_stop_status,
            name="ChkStopThr",
            daemon=True,
        )

        self._network_status_lock = threading.Lock()
        self._network_status_handle = None
        self._network_status_thread = threading.Thread(
            target=self.check_network_status,
            name="NetStatThr",
            daemon=True,
        )

        self._internal_messages_lock = threading.Lock()
        self._internal_messages_handle = None
        self._internal_messages_thread = threading.Thread(
            target=self.check_internal_messages,
            name="IntMsgThr",
            daemon=True,
        )

    def start(self) -> None:
        self._stop_thread.start()
        self._network_status_thread.start()
        self._internal_messages_thread.start()

    @staticmethod
    def _abandon_status_check(
        lock: threading.Lock,
        handle: Optional[MailboxHandle],
    ):
        with lock:
            if handle:
                handle.abandon()

    def _loop_check_status(
        self,
        *,
        lock: threading.Lock,
        set_handle: Any,
        timeout: int,
        request: Any,
        process: Any,
    ) -> None:
        local_handle: Optional[MailboxHandle] = None
        join_requested = False
        while not join_requested:
            time_probe = time.monotonic()
            if not local_handle:
                local_handle = request()
            assert local_handle

            with lock:
                if self._join_event.is_set():
                    break
                set_handle(local_handle)
            try:
                result = local_handle.wait(timeout=timeout, release=False)
            except MailboxError:
                # background threads are oportunistically getting results
                # from the internal process but the internal process could
                # be shutdown at any time.  In this case assume that the
                # thread should exit silently.   This is possible
                # because we do not have an atexit handler for the user
                # process which quiesces active threads.
                break
            with lock:
                set_handle(None)

            if result:
                process(result)
                # if request finished, clear the handle to send on the next interval
                local_handle.abandon()
                local_handle = None

            time_elapsed = time.monotonic() - time_probe
            wait_time = max(timeout - time_elapsed, 0)
            join_requested = self._join_event.wait(timeout=wait_time)

    def check_network_status(self) -> None:
        def _process_network_status(result: Result) -> None:
            network_status = result.response.network_status_response
            for hr in network_status.network_responses:
                if (
                    hr.http_status_code == 200 or hr.http_status_code == 0
                ):  # we use 0 for non-http errors (eg wandb errors)
                    wandb.termlog(f"{hr.http_response_text}")
                else:
                    wandb.termlog(
                        "{} encountered ({}), retrying request".format(
                            hr.http_status_code, hr.http_response_text.rstrip()
                        )
                    )

        try:
            self._loop_check_status(
                lock=self._network_status_lock,
                set_handle=lambda x: setattr(self, "_network_status_handle", x),
                timeout=self._retry_polling_interval,
                request=self._interface.deliver_network_status,
                process=_process_network_status,
            )
        except BrokenPipeError:
            self._abandon_status_check(
                self._network_status_lock,
                self._network_status_handle,
            )

    def check_stop_status(self) -> None:
        def _process_stop_status(result: Result) -> None:
            stop_status = result.response.stop_status_response
            if stop_status.run_should_stop:
                # TODO(frz): This check is required
                # until WB-3606 is resolved on server side.
                if not wandb.agents.pyagent.is_running():  # type: ignore
                    thread.interrupt_main()
                    return

        try:
            self._loop_check_status(
                lock=self._stop_status_lock,
                set_handle=lambda x: setattr(self, "_stop_status_handle", x),
                timeout=self._stop_polling_interval,
                request=self._interface.deliver_stop_status,
                process=_process_stop_status,
            )
        except BrokenPipeError:
            self._abandon_status_check(
                self._stop_status_lock,
                self._stop_status_handle,
            )

    def check_internal_messages(self) -> None:
        def _process_internal_messages(result: Result) -> None:
            internal_messages = result.response.internal_messages_response
            for msg in internal_messages.messages.warning:
                wandb.termwarn(msg)

        try:
            self._loop_check_status(
                lock=self._internal_messages_lock,
                set_handle=lambda x: setattr(self, "_internal_messages_handle", x),
                timeout=self._internal_messages_polling_interval,
                request=self._interface.deliver_internal_messages,
                process=_process_internal_messages,
            )
        except BrokenPipeError:
            self._abandon_status_check(
                self._internal_messages_lock,
                self._internal_messages_handle,
            )

    def stop(self) -> None:
        self._join_event.set()
        self._abandon_status_check(
            self._stop_status_lock,
            self._stop_status_handle,
        )
        self._abandon_status_check(
            self._network_status_lock,
            self._network_status_handle,
        )
        self._abandon_status_check(
            self._internal_messages_lock,
            self._internal_messages_handle,
        )

    def join(self) -> None:
        self.stop()
        self._stop_thread.join()
        self._network_status_thread.join()
        self._internal_messages_thread.join()


class _run_decorator:  # noqa: N801
    _is_attaching: str = ""

    class Dummy: ...

    @classmethod
    def _attach(cls, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self: Type["Run"], *args: Any, **kwargs: Any) -> Any:
            # * `_attach_id` is only assigned in service hence for all non-service cases
            # it will be a passthrough.
            # * `_attach_pid` is only assigned in _init (using _attach_pid guarantees single attach):
            #   - for non-fork case the object is shared through pickling so will be None.
            #   - for fork case the new process share mem space hence the value would be of parent process.
            if (
                getattr(self, "_attach_id", None)
                and getattr(self, "_attach_pid", None) != os.getpid()
            ):
                if cls._is_attaching:
                    message = (
                        f"Trying to attach `{func.__name__}` "
                        f"while in the middle of attaching `{cls._is_attaching}`"
                    )
                    raise RuntimeError(message)
                cls._is_attaching = func.__name__
                try:
                    wandb._attach(run=self)  # type: ignore
                except Exception as e:
                    # In case the attach fails we will raise the exception that caused the issue.
                    # This exception should be caught and fail the execution of the program.
                    cls._is_attaching = ""
                    raise e
                cls._is_attaching = ""
            return func(self, *args, **kwargs)

        return wrapper

    @classmethod
    def _noop_on_finish(cls, message: str = "", only_warn: bool = False) -> Callable:
        def decorator_fn(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper_fn(self: Type["Run"], *args: Any, **kwargs: Any) -> Any:
                if not getattr(self, "_is_finished", False):
                    return func(self, *args, **kwargs)

                default_message = (
                    f"Run ({self.id}) is finished. The call to `{func.__name__}` will be ignored. "
                    f"Please make sure that you are using an active run."
                )
                resolved_message = message or default_message
                if only_warn:
                    warnings.warn(resolved_message, UserWarning, stacklevel=2)
                else:
                    raise errors.UsageError(resolved_message)

            return wrapper_fn

        return decorator_fn

    @classmethod
    def _noop(cls, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self: Type["Run"], *args: Any, **kwargs: Any) -> Any:
            # `_attach_id` is only assigned in service hence for all service cases
            # it will be a passthrough. We don't pickle non-service so again a way
            # to see that we are in non-service case
            if getattr(self, "_attach_id", None) is None:
                # `_init_pid` is only assigned in __init__ (this will be constant check for mp):
                #   - for non-fork case the object is shared through pickling,
                #     and we don't pickle non-service so will be None
                #   - for fork case the new process share mem space hence the value would be of parent process.
                _init_pid = getattr(self, "_init_pid", None)
                if _init_pid != os.getpid():
                    message = "`{}` ignored (called from pid={}, `init` called from pid={}). See: {}".format(
                        func.__name__,
                        os.getpid(),
                        _init_pid,
                        wburls.get("multiprocess"),
                    )
                    # - if this process was pickled in non-service case,
                    #   we ignore the attributes (since pickle is not supported)
                    # - for fork case will use the settings of the parent process
                    # - only point of inconsistent behavior from forked and non-forked cases
                    settings = getattr(self, "_settings", None)
                    if settings and settings["strict"]:
                        wandb.termerror(message, repeat=False)
                        raise errors.UnsupportedError(
                            f"`{func.__name__}` does not support multiprocessing"
                        )
                    wandb.termwarn(message, repeat=False)
                    return cls.Dummy()

            return func(self, *args, **kwargs)

        return wrapper


@dataclass
class RunStatus:
    sync_items_total: int = field(default=0)
    sync_items_pending: int = field(default=0)
    sync_time: Optional[datetime] = field(default=None)


class Run:
    """A unit of computation logged by wandb. Typically, this is an ML experiment.

    Create a run with `wandb.init()`:
    <!--yeadoc-test:run-object-basic-->
    ```python
    import wandb

    run = wandb.init()
    ```

    There is only ever at most one active `wandb.Run` in any process,
    and it is accessible as `wandb.run`:
    <!--yeadoc-test:global-run-object-->
    ```python
    import wandb

    assert wandb.run is None

    wandb.init()

    assert wandb.run is not None
    ```
    anything you log with `wandb.log` will be sent to that run.

    If you want to start more runs in the same script or notebook, you'll need to
    finish the run that is in-flight. Runs can be finished with `wandb.finish` or
    by using them in a `with` block:
    <!--yeadoc-test:run-context-manager-->
    ```python
    import wandb

    wandb.init()
    wandb.finish()

    assert wandb.run is None

    with wandb.init() as run:
        pass  # log data here

    assert wandb.run is None
    ```

    See the documentation for `wandb.init` for more on creating runs, or check out
    [our guide to `wandb.init`](https://docs.wandb.ai/guides/track/launch).

    In distributed training, you can either create a single run in the rank 0 process
    and then log information only from that process, or you can create a run in each process,
    logging from each separately, and group the results together with the `group` argument
    to `wandb.init`. For more details on distributed training with W&B, check out
    [our guide](https://docs.wandb.ai/guides/track/log/distributed-training).

    Currently, there is a parallel `Run` object in the `wandb.Api`. Eventually these
    two objects will be merged.

    Attributes:
        summary: (Summary) Single values set for each `wandb.log()` key. By
            default, summary is set to the last value logged. You can manually
            set summary to the best value, like max accuracy, instead of the
            final value.
    """

    _telemetry_obj: telemetry.TelemetryRecord
    _telemetry_obj_active: bool
    _telemetry_obj_dirty: bool
    _telemetry_obj_flushed: bytes

    _teardown_hooks: List[TeardownHook]
    _tags: Optional[Tuple[Any, ...]]

    _entity: Optional[str]
    _project: Optional[str]
    _group: Optional[str]
    _job_type: Optional[str]
    _name: Optional[str]
    _notes: Optional[str]
    _sweep_id: Optional[str]

    _run_obj: Optional[RunRecord]
    # Use string literal annotation because of type reference loop
    _backend: Optional["wandb.sdk.backend.backend.Backend"]
    _internal_run_interface: Optional[
        "wandb.sdk.interface.interface_queue.InterfaceQueue"
    ]
    _wl: Optional[_WandbSetup]

    _out_redir: Optional[redirect.RedirectBase]
    _err_redir: Optional[redirect.RedirectBase]
    _redirect_cb: Optional[Callable[[str, str], None]]
    _redirect_raw_cb: Optional[Callable[[str, str], None]]
    _output_writer: Optional["filesystem.CRDedupedFile"]
    _quiet: Optional[bool]

    _atexit_cleanup_called: bool
    _hooks: Optional[ExitHooks]
    _exit_code: Optional[int]

    _run_status_checker: Optional[RunStatusChecker]

    _sampled_history: Optional["SampledHistoryResponse"]
    _final_summary: Optional["GetSummaryResponse"]
    _poll_exit_handle: Optional[MailboxHandle]
    _poll_exit_response: Optional[PollExitResponse]
    _internal_messages_response: Optional["InternalMessagesResponse"]

    _stdout_slave_fd: Optional[int]
    _stderr_slave_fd: Optional[int]
    _artifact_slots: List[str]

    _init_pid: int
    _attach_pid: int
    _iface_pid: Optional[int]
    _iface_port: Optional[int]

    _attach_id: Optional[str]
    _is_attached: bool
    _is_finished: bool
    _settings: Settings

    _launch_artifacts: Optional[Dict[str, Any]]
    _printer: Union["PrinterTerm", "PrinterJupyter"]

    def __init__(
        self,
        settings: Settings,
        config: Optional[Dict[str, Any]] = None,
        sweep_config: Optional[Dict[str, Any]] = None,
        launch_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        # pid is set, so we know if this run object was initialized by this process
        self._init_pid = os.getpid()

        if settings._noop:
            # TODO: properly handle setting for disabled mode
            self._settings = settings
            return

        self._init(
            settings=settings,
            config=config,
            sweep_config=sweep_config,
            launch_config=launch_config,
        )

    def _init(
        self,
        settings: Settings,
        config: Optional[Dict[str, Any]] = None,
        sweep_config: Optional[Dict[str, Any]] = None,
        launch_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._settings = settings

        self._config = wandb_config.Config()
        self._config._set_callback(self._config_callback)
        self._config._set_artifact_callback(self._config_artifact_callback)
        self._config._set_settings(self._settings)
        self._backend = None
        self._internal_run_interface = None
        # todo: perhaps this should be a property that is a noop on a finished run
        self.summary = wandb_summary.Summary(
            self._summary_get_current_summary_callback,
        )
        self.summary._set_update_callback(self._summary_update_callback)
        self._step = 0
        self._torch_history: Optional[wandb_torch.TorchHistory] = None  # type: ignore

        # todo: eventually would be nice to make this configurable using self._settings._start_time
        #  need to test (jhr): if you set start time to 2 days ago and run a test for 15 minutes,
        #  does the total time get calculated right (not as 2 days and 15 minutes)?
        self._start_time = time.time()

        _datatypes_set_callback(self._datatypes_callback)

        self._printer = get_printer(self._settings._jupyter)
        self._wl = None
        self._reporter: Optional[Reporter] = None

        self._entity = None
        self._project = None
        self._group = None
        self._job_type = None
        self._run_id = self._settings.run_id
        self._starting_step = 0
        self._name = None
        self._notes = None
        self._tags = None
        self._remote_url = None
        self._commit = None
        self._sweep_id = None

        self._hooks = None
        self._teardown_hooks = []
        self._out_redir = None
        self._err_redir = None
        self._stdout_slave_fd = None
        self._stderr_slave_fd = None
        self._exit_code = None
        self._exit_result = None
        self._quiet = self._settings.quiet

        self._output_writer = None
        self._used_artifact_slots: Dict[str, str] = {}

        # Returned from backend request_run(), set from wandb_init?
        self._run_obj = None

        # Created when the run "starts".
        self._run_status_checker = None

        self._sampled_history = None
        self._final_summary = None
        self._poll_exit_response = None
        self._internal_messages_response = None
        self._poll_exit_handle = None

        # Initialize telemetry object
        self._telemetry_obj = telemetry.TelemetryRecord()
        self._telemetry_obj_active = False
        self._telemetry_obj_flushed = b""
        self._telemetry_obj_dirty = False

        self._atexit_cleanup_called = False

        # Pull info from settings
        self._init_from_settings(self._settings)

        # Initial scope setup for sentry.
        # This might get updated when the actual run comes back.
        wandb._sentry.configure_scope(
            tags=dict(self._settings),
            process_context="user",
        )

        # Populate config
        config = config or dict()
        wandb_key = "_wandb"
        config.setdefault(wandb_key, dict())
        self._launch_artifact_mapping: Dict[str, Any] = {}
        self._unique_launch_artifact_sequence_names: Dict[str, Any] = {}
        if self._settings.save_code and self._settings.program_relpath:
            config[wandb_key]["code_path"] = LogicalPath(
                os.path.join("code", self._settings.program_relpath)
            )

        if self._settings.fork_from is not None:
            config[wandb_key]["branch_point"] = {
                "run_id": self._settings.fork_from.run,
                "step": self._settings.fork_from.value,
            }

        if self._settings.resume_from is not None:
            config[wandb_key]["branch_point"] = {
                "run_id": self._settings.resume_from.run,
                "step": self._settings.resume_from.value,
            }

        self._config._update(config, ignore_locked=True)

        if sweep_config:
            self._config.merge_locked(
                sweep_config, user="sweep", _allow_val_change=True
            )

        if launch_config:
            self._config.merge_locked(
                launch_config, user="launch", _allow_val_change=True
            )

        # if run is from a launch queue, add queue id to _wandb config
        launch_queue_name = wandb.env.get_launch_queue_name()
        if launch_queue_name:
            self._config[wandb_key]["launch_queue_name"] = launch_queue_name

        launch_queue_entity = wandb.env.get_launch_queue_entity()
        if launch_queue_entity:
            self._config[wandb_key]["launch_queue_entity"] = launch_queue_entity

        launch_trace_id = wandb.env.get_launch_trace_id()
        if launch_trace_id:
            self._config[wandb_key]["launch_trace_id"] = launch_trace_id

        # interface pid and port configured when backend is configured (See _hack_set_run)
        # TODO: using pid isn't the best for windows as pid reuse can happen more often than unix
        self._iface_pid = None
        self._iface_port = None
        self._attach_id = None
        self._is_attached = False
        self._is_finished = False

        self._attach_pid = os.getpid()

        # for now, use runid as attach id, this could/should be versioned in the future
        if not self._settings._disable_service:
            self._attach_id = self._settings.run_id

    def _set_iface_pid(self, iface_pid: int) -> None:
        self._iface_pid = iface_pid

    def _set_iface_port(self, iface_port: int) -> None:
        self._iface_port = iface_port

    def _handle_launch_artifact_overrides(self) -> None:
        if self._settings.launch and (os.environ.get("WANDB_ARTIFACTS") is not None):
            try:
                artifacts: Dict[str, Any] = json.loads(
                    os.environ.get("WANDB_ARTIFACTS", "{}")
                )
            except (ValueError, SyntaxError):
                wandb.termwarn("Malformed WANDB_ARTIFACTS, using original artifacts")
            else:
                self._initialize_launch_artifact_maps(artifacts)

        elif (
            self._settings.launch
            and self._settings.launch_config_path
            and os.path.exists(self._settings.launch_config_path)
        ):
            self.save(self._settings.launch_config_path)
            with open(self._settings.launch_config_path) as fp:
                launch_config = json.loads(fp.read())
            if launch_config.get("overrides", {}).get("artifacts") is not None:
                artifacts = launch_config.get("overrides").get("artifacts")
                self._initialize_launch_artifact_maps(artifacts)

    def _initialize_launch_artifact_maps(self, artifacts: Dict[str, Any]) -> None:
        for key, item in artifacts.items():
            self._launch_artifact_mapping[key] = item
            artifact_sequence_tuple_or_slot = key.split(":")

            if len(artifact_sequence_tuple_or_slot) == 2:
                sequence_name = artifact_sequence_tuple_or_slot[0].split("/")[-1]
                if self._unique_launch_artifact_sequence_names.get(sequence_name):
                    self._unique_launch_artifact_sequence_names.pop(sequence_name)
                else:
                    self._unique_launch_artifact_sequence_names[sequence_name] = item

    def _telemetry_callback(self, telem_obj: telemetry.TelemetryRecord) -> None:
        if not hasattr(self, "_telemetry_obj"):
            return
        self._telemetry_obj.MergeFrom(telem_obj)
        self._telemetry_obj_dirty = True
        self._telemetry_flush()

    def _telemetry_flush(self) -> None:
        if not hasattr(self, "_telemetry_obj"):
            return
        if not self._telemetry_obj_active:
            return
        if not self._telemetry_obj_dirty:
            return
        if self._backend and self._backend.interface:
            serialized = self._telemetry_obj.SerializeToString()
            if serialized == self._telemetry_obj_flushed:
                return
            self._backend.interface._publish_telemetry(self._telemetry_obj)
            self._telemetry_obj_flushed = serialized
            self._telemetry_obj_dirty = False

    def _freeze(self) -> None:
        self._frozen = True

    def __setattr__(self, attr: str, value: object) -> None:
        if getattr(self, "_frozen", None) and not hasattr(self, attr):
            raise Exception(f"Attribute {attr} is not supported on Run object.")
        super().__setattr__(attr, value)

    def _update_settings(self, settings: Settings) -> None:
        self._settings = settings
        self._init_from_settings(settings)

    def _init_from_settings(self, settings: Settings) -> None:
        if settings.entity is not None:
            self._entity = settings.entity
        if settings.project is not None:
            self._project = settings.project
        if settings.run_group is not None:
            self._group = settings.run_group
        if settings.run_job_type is not None:
            self._job_type = settings.run_job_type
        if settings.run_name is not None:
            self._name = settings.run_name
        if settings.run_notes is not None:
            self._notes = settings.run_notes
        if settings.run_tags is not None:
            self._tags = settings.run_tags
        if settings.sweep_id is not None:
            self._sweep_id = settings.sweep_id

    def _make_proto_run(self, run: RunRecord) -> None:
        """Populate protocol buffer RunData for interface/interface."""
        if self._entity is not None:
            run.entity = self._entity
        if self._project is not None:
            run.project = self._project
        if self._group is not None:
            run.run_group = self._group
        if self._job_type is not None:
            run.job_type = self._job_type
        if self._run_id is not None:
            run.run_id = self._run_id
        if self._name is not None:
            run.display_name = self._name
        if self._notes is not None:
            run.notes = self._notes
        if self._tags is not None:
            for tag in self._tags:
                run.tags.append(tag)
        if self._start_time is not None:
            run.start_time.FromMicroseconds(int(self._start_time * 1e6))
        if self._remote_url is not None:
            run.git.remote_url = self._remote_url
        if self._commit is not None:
            run.git.commit = self._commit
        if self._sweep_id is not None:
            run.sweep_id = self._sweep_id
        # Note: run.config is set in interface/interface:_make_run()

    def _populate_git_info(self) -> None:
        # Use user provided git info if available otherwise resolve it from the environment
        try:
            repo = GitRepo(
                root=self._settings.git_root,
                remote=self._settings.git_remote,
                remote_url=self._settings.git_remote_url,
                commit=self._settings.git_commit,
                lazy=False,
            )
            self._remote_url, self._commit = repo.remote_url, repo.last_commit
        except Exception:
            wandb.termwarn("Cannot find valid git repo associated with this directory.")

    def __deepcopy__(self, memo: Dict[int, Any]) -> "Run":
        return self

    def __getstate__(self) -> Any:
        """Return run state as a custom pickle."""
        # We only pickle in service mode
        if not self._settings or self._settings._disable_service:
            return

        _attach_id = self._attach_id
        if not _attach_id:
            return

        return dict(
            _attach_id=_attach_id,
            _init_pid=self._init_pid,
            _is_finished=self._is_finished,
        )

    def __setstate__(self, state: Any) -> None:
        """Set run state from a custom pickle."""
        if not state:
            return

        _attach_id = state.get("_attach_id")
        if not _attach_id:
            return

        if state["_init_pid"] == os.getpid():
            raise RuntimeError("attach in the same process is not supported currently")

        self.__dict__.update(state)

    @property
    def _torch(self) -> "wandb_torch.TorchHistory":  # type: ignore
        if self._torch_history is None:
            self._torch_history = wandb_torch.TorchHistory()  # type: ignore
        return self._torch_history

    @property
    @_run_decorator._attach
    def settings(self) -> Settings:
        """A frozen copy of run's Settings object."""
        cp = self._settings.copy()
        cp.freeze()
        return cp

    @property
    @_run_decorator._attach
    def dir(self) -> str:
        """The directory where files associated with the run are saved."""
        return self._settings.files_dir

    @property
    @_run_decorator._attach
    def config(self) -> wandb_config.Config:
        """Config object associated with this run."""
        return self._config

    @property
    @_run_decorator._attach
    def config_static(self) -> wandb_config.ConfigStatic:
        return wandb_config.ConfigStatic(self._config)

    @property
    @_run_decorator._attach
    def name(self) -> Optional[str]:
        """Display name of the run.

        Display names are not guaranteed to be unique and may be descriptive.
        By default, they are randomly generated.
        """
        if self._name:
            return self._name
        if not self._run_obj:
            return None
        return self._run_obj.display_name

    @name.setter
    @_run_decorator._noop_on_finish()
    def name(self, name: str) -> None:
        with telemetry.context(run=self) as tel:
            tel.feature.set_run_name = True
        self._name = name
        if self._backend and self._backend.interface:
            self._backend.interface.publish_run(self)

    @property
    @_run_decorator._attach
    def notes(self) -> Optional[str]:
        """Notes associated with the run, if there are any.

        Notes can be a multiline string and can also use markdown and latex equations
        inside `$$`, like `$x + 3$`.
        """
        if self._notes:
            return self._notes
        if not self._run_obj:
            return None
        return self._run_obj.notes

    @notes.setter
    @_run_decorator._noop_on_finish()
    def notes(self, notes: str) -> None:
        self._notes = notes
        if self._backend and self._backend.interface:
            self._backend.interface.publish_run(self)

    @property
    @_run_decorator._attach
    def tags(self) -> Optional[Tuple]:
        """Tags associated with the run, if there are any."""
        if self._tags:
            return self._tags
        if self._run_obj:
            return tuple(self._run_obj.tags)
        return None

    @tags.setter
    @_run_decorator._noop_on_finish()
    def tags(self, tags: Sequence) -> None:
        with telemetry.context(run=self) as tel:
            tel.feature.set_run_tags = True
        self._tags = tuple(tags)
        if self._backend and self._backend.interface:
            self._backend.interface.publish_run(self)

    @property
    @_run_decorator._attach
    def id(self) -> str:
        """Identifier for this run."""
        if TYPE_CHECKING:
            assert self._run_id is not None
        return self._run_id

    @property
    @_run_decorator._attach
    def sweep_id(self) -> Optional[str]:
        """ID of the sweep associated with the run, if there is one."""
        if not self._run_obj:
            return None
        return self._run_obj.sweep_id or None

    def _get_path(self) -> str:
        parts = [
            e for e in [self._entity, self._project, self._run_id] if e is not None
        ]
        return "/".join(parts)

    @property
    @_run_decorator._attach
    def path(self) -> str:
        """Path to the run.

        Run paths include entity, project, and run ID, in the format
        `entity/project/run_id`.
        """
        return self._get_path()

    def _get_start_time(self) -> float:
        return (
            self._start_time
            if not self._run_obj
            else (self._run_obj.start_time.ToMicroseconds() / 1e6)
        )

    @property
    @_run_decorator._attach
    def start_time(self) -> float:
        """Unix timestamp (in seconds) of when the run started."""
        return self._get_start_time()

    def _get_starting_step(self) -> int:
        return self._starting_step if not self._run_obj else self._run_obj.starting_step

    @property
    @_run_decorator._attach
    def starting_step(self) -> int:
        """The first step of the run."""
        return self._get_starting_step()

    @property
    @_run_decorator._attach
    def resumed(self) -> bool:
        """True if the run was resumed, False otherwise."""
        return self._run_obj.resumed if self._run_obj else False

    @property
    @_run_decorator._attach
    def step(self) -> int:
        """Current value of the step.

        This counter is incremented by `wandb.log`.
        """
        return self._step

    def project_name(self) -> str:
        # TODO: deprecate this in favor of project
        return self._run_obj.project if self._run_obj else ""

    @property
    @_run_decorator._attach
    def mode(self) -> str:
        """For compatibility with `0.9.x` and earlier, deprecate eventually."""
        if hasattr(self, "_telemetry_obj"):
            deprecate.deprecate(
                field_name=deprecate.Deprecated.run__mode,
                warning_message=(
                    "The mode property of wandb.run is deprecated "
                    "and will be removed in a future release."
                ),
            )
        return "dryrun" if self._settings._offline else "run"

    @property
    @_run_decorator._attach
    def offline(self) -> bool:
        return self._settings._offline

    @property
    @_run_decorator._attach
    def disabled(self) -> bool:
        return self._settings._noop

    def _get_group(self) -> str:
        return self._run_obj.run_group if self._run_obj else ""

    @property
    @_run_decorator._attach
    def group(self) -> str:
        """Name of the group associated with the run.

        Setting a group helps the W&B UI organize runs in a sensible way.

        If you are doing a distributed training you should give all of the
            runs in the training the same group.
        If you are doing cross-validation you should give all the cross-validation
            folds the same group.
        """
        return self._get_group()

    @property
    @_run_decorator._attach
    def job_type(self) -> str:
        return self._run_obj.job_type if self._run_obj else ""

    @property
    @_run_decorator._attach
    def project(self) -> str:
        """Name of the W&B project associated with the run."""
        return self.project_name()

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def log_code(
        self,
        root: Optional[str] = ".",
        name: Optional[str] = None,
        include_fn: Union[
            Callable[[str, str], bool], Callable[[str], bool]
        ] = _is_py_requirements_or_dockerfile,
        exclude_fn: Union[
            Callable[[str, str], bool], Callable[[str], bool]
        ] = filenames.exclude_wandb_fn,
    ) -> Optional[Artifact]:
        """Save the current state of your code to a W&B Artifact.

        By default, it walks the current directory and logs all files that end with `.py`.

        Arguments:
            root: The relative (to `os.getcwd()`) or absolute path to recursively find code from.
            name: (str, optional) The name of our code artifact. By default, we'll name
                the artifact `source-$PROJECT_ID-$ENTRYPOINT_RELPATH`. There may be scenarios where you want
                many runs to share the same artifact. Specifying name allows you to achieve that.
            include_fn: A callable that accepts a file path and (optionally) root path and
                returns True when it should be included and False otherwise. This
                defaults to: `lambda path, root: path.endswith(".py")`
            exclude_fn: A callable that accepts a file path and (optionally) root path and
                returns `True` when it should be excluded and `False` otherwise. This
                defaults to a function that excludes all files within `<root>/.wandb/`
                and `<root>/wandb/` directories.

        Examples:
            Basic usage
            ```python
            run.log_code()
            ```

            Advanced usage
            ```python
            run.log_code(
                "../",
                include_fn=lambda path: path.endswith(".py") or path.endswith(".ipynb"),
                exclude_fn=lambda path, root: os.path.relpath(path, root).startswith("cache/"),
            )
            ```

        Returns:
            An `Artifact` object if code was logged
        """
        if name is None:
            if self.settings._jupyter:
                notebook_name = None
                if self.settings.notebook_name:
                    notebook_name = self.settings.notebook_name
                elif self.settings._jupyter_path:
                    if self.settings._jupyter_path.startswith("fileId="):
                        notebook_name = self.settings._jupyter_name
                    else:
                        notebook_name = self.settings._jupyter_path
                name_string = f"{self._project}-{notebook_name}"
            else:
                name_string = f"{self._project}-{self._settings.program_relpath}"
            name = wandb.util.make_artifact_name_safe(f"source-{name_string}")
        art = wandb.Artifact(name, "code")
        files_added = False
        if root is not None:
            root = os.path.abspath(root)
            for file_path in filenames.filtered_dir(root, include_fn, exclude_fn):
                files_added = True
                save_name = os.path.relpath(file_path, root)
                art.add_file(file_path, name=save_name)
        # Add any manually staged files such as ipynb notebooks
        for dirpath, _, files in os.walk(self._settings._tmp_code_dir):
            for fname in files:
                file_path = os.path.join(dirpath, fname)
                save_name = os.path.relpath(file_path, self._settings._tmp_code_dir)
                files_added = True
                art.add_file(file_path, name=save_name)
        if not files_added:
            wandb.termwarn(
                "No relevant files were detected in the specified directory. No code will be logged to your run."
            )
            return None

        return self._log_artifact(art)

    def get_url(self) -> Optional[str]:
        """Return the url for the W&B run, if there is one.

        Offline runs will not have a url.
        """
        if self._settings._offline:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._settings.run_url

    def get_project_url(self) -> Optional[str]:
        """Return the url for the W&B project associated with the run, if there is one.

        Offline runs will not have a project url.
        """
        if self._settings._offline:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._settings.project_url

    def get_sweep_url(self) -> Optional[str]:
        """Return the url for the sweep associated with the run, if there is one."""
        if self._settings._offline:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._settings.sweep_url

    @property
    @_run_decorator._attach
    def url(self) -> Optional[str]:
        """The W&B url associated with the run."""
        return self.get_url()

    @property
    @_run_decorator._attach
    def entity(self) -> str:
        """The name of the W&B entity associated with the run.

        Entity can be a username or the name of a team or organization.
        """
        return self._entity or ""

    def _label_internal(
        self,
        code: Optional[str] = None,
        repo: Optional[str] = None,
        code_version: Optional[str] = None,
    ) -> None:
        with telemetry.context(run=self) as tel:
            if code and RE_LABEL.match(code):
                tel.label.code_string = code
            if repo and RE_LABEL.match(repo):
                tel.label.repo_string = repo
            if code_version and RE_LABEL.match(code_version):
                tel.label.code_version = code_version

    def _label(
        self,
        code: Optional[str] = None,
        repo: Optional[str] = None,
        code_version: Optional[str] = None,
        **kwargs: str,
    ) -> None:
        if self._settings.label_disable:
            return
        for k, v in (("code", code), ("repo", repo), ("code_version", code_version)):
            if v and not RE_LABEL.match(v):
                wandb.termwarn(
                    f"Label added for '{k}' with invalid identifier '{v}' (ignored).",
                    repeat=False,
                )
        for v in kwargs:
            wandb.termwarn(
                f"Label added for unsupported key {v!r} (ignored).",
                repeat=False,
            )

        self._label_internal(code=code, repo=repo, code_version=code_version)

        # update telemetry in the backend immediately for _label() callers
        self._telemetry_flush()

    def _label_probe_lines(self, lines: List[str]) -> None:
        if not lines:
            return
        parsed = telemetry._parse_label_lines(lines)
        if not parsed:
            return
        label_dict = {}
        code = parsed.get("code") or parsed.get("c")
        if code:
            label_dict["code"] = code
        repo = parsed.get("repo") or parsed.get("r")
        if repo:
            label_dict["repo"] = repo
        code_ver = parsed.get("version") or parsed.get("v")
        if code_ver:
            label_dict["code_version"] = code_ver
        self._label_internal(**label_dict)

    def _label_probe_main(self) -> None:
        m = sys.modules.get("__main__")
        if not m:
            return
        doc = getattr(m, "__doc__", None)
        if not doc:
            return

        doclines = doc.splitlines()
        self._label_probe_lines(doclines)

    # TODO: annotate jupyter Notebook class
    def _label_probe_notebook(self, notebook: Any) -> None:
        logger.info("probe notebook")
        lines = None
        try:
            data = notebook.probe_ipynb()
            cell0 = data.get("cells", [])[0]
            lines = cell0.get("source")
            # kaggle returns a string instead of a list
            if isinstance(lines, str):
                lines = lines.split()
        except Exception as e:
            logger.info(f"Unable to probe notebook: {e}")
            return
        if lines:
            self._label_probe_lines(lines)

    @_run_decorator._attach
    def display(self, height: int = 420, hidden: bool = False) -> bool:
        """Display this run in jupyter."""
        if self._settings._jupyter:
            ipython.display_html(self.to_html(height, hidden))
            return True
        else:
            wandb.termwarn(".display() only works in jupyter environments")
            return False

    @_run_decorator._attach
    def to_html(self, height: int = 420, hidden: bool = False) -> str:
        """Generate HTML containing an iframe displaying the current run."""
        url = self._settings.run_url + "?jupyter=true"
        style = f"border:none;width:100%;height:{height}px;"
        prefix = ""
        if hidden:
            style += "display:none;"
            prefix = ipython.toggle_button()
        return prefix + f"<iframe src={url!r} style={style!r}></iframe>"

    def _repr_mimebundle_(
        self, include: Optional[Any] = None, exclude: Optional[Any] = None
    ) -> Dict[str, str]:
        return {"text/html": self.to_html(hidden=True)}

    @_run_decorator._noop_on_finish()
    def _config_callback(
        self,
        key: Optional[Union[Tuple[str, ...], str]] = None,
        val: Optional[Any] = None,
        data: Optional[Dict[str, object]] = None,
    ) -> None:
        logger.info(f"config_cb {key} {val} {data}")
        if self._backend and self._backend.interface:
            self._backend.interface.publish_config(key=key, val=val, data=data)

    def _config_artifact_callback(
        self, key: str, val: Union[str, Artifact, dict]
    ) -> Artifact:
        # artifacts can look like dicts as they are passed into the run config
        # since the run config stores them on the backend as a dict with fields shown
        # in wandb.util.artifact_to_json
        if _is_artifact_version_weave_dict(val):
            assert isinstance(val, dict)
            public_api = self._public_api()
            artifact = Artifact._from_id(val["id"], public_api.client)
            return self.use_artifact(artifact, use_as=key)
        elif _is_artifact_string(val):
            # this will never fail, but is required to make mypy happy
            assert isinstance(val, str)
            artifact_string, base_url, is_id = parse_artifact_string(val)
            overrides = {}
            if base_url is not None:
                overrides = {"base_url": base_url}
                public_api = public.Api(overrides)
            else:
                public_api = self._public_api()
            if is_id:
                artifact = Artifact._from_id(artifact_string, public_api._client)
            else:
                artifact = public_api.artifact(name=artifact_string)
            # in the future we'll need to support using artifacts from
            # different instances of wandb.

            return self.use_artifact(artifact, use_as=key)
        elif _is_artifact_object(val):
            return self.use_artifact(val, use_as=key)
        else:
            raise ValueError(
                f"Cannot call _config_artifact_callback on type {type(val)}"
            )

    def _set_config_wandb(self, key: str, val: Any) -> None:
        self._config_callback(key=("_wandb", key), val=val)

    @_run_decorator._noop_on_finish()
    def _summary_update_callback(self, summary_record: SummaryRecord) -> None:
        with telemetry.context(run=self) as tel:
            tel.feature.set_summary = True
        if self._backend and self._backend.interface:
            self._backend.interface.publish_summary(summary_record)

    def _on_progress_get_summary(self, handle: MailboxProgress) -> None:
        pass
        # TODO(jhr): enable printing for get_summary in later mailbox dev phase
        # line = "Waiting for run.summary data..."
        # self._printer.display(line)

    def _summary_get_current_summary_callback(self) -> Dict[str, Any]:
        if self._is_finished:
            # TODO: WB-18420: fetch summary from backend and stage it before run is finished
            wandb.termwarn("Summary data not available in finished run")
            return {}
        if not self._backend or not self._backend.interface:
            return {}
        handle = self._backend.interface.deliver_get_summary()
        result = handle.wait(
            timeout=self._settings.summary_timeout,
            on_progress=self._on_progress_get_summary,
        )
        if not result:
            return {}
        get_summary_response = result.response.get_summary_response
        return proto_util.dict_from_proto_list(get_summary_response.item)

    def _metric_callback(self, metric_record: MetricRecord) -> None:
        if self._backend and self._backend.interface:
            self._backend.interface._publish_metric(metric_record)

    def _datatypes_callback(self, fname: str) -> None:
        if not self._backend or not self._backend.interface:
            return
        files: FilesDict = dict(files=[(GlobStr(glob.escape(fname)), "now")])
        self._backend.interface.publish_files(files)

    def _visualization_hack(self, row: Dict[str, Any]) -> Dict[str, Any]:
        # TODO(jhr): move visualize hack somewhere else
        chart_keys = set()
        split_table_set = set()
        for k in row:
            if isinstance(row[k], Visualize):
                key = row[k].get_config_key(k)
                value = row[k].get_config_value(k)
                row[k] = row[k]._data
                self._config_callback(val=value, key=key)
            elif isinstance(row[k], CustomChart):
                chart_keys.add(k)
                key = row[k].get_config_key(k)
                if row[k]._split_table:
                    value = row[k].get_config_value(
                        "Vega2", row[k].user_query(f"Custom Chart Tables/{k}_table")
                    )
                    split_table_set.add(k)
                else:
                    value = row[k].get_config_value(
                        "Vega2", row[k].user_query(f"{k}_table")
                    )
                row[k] = row[k]._data
                self._config_callback(val=value, key=key)

        for k in chart_keys:
            # remove the chart key from the row
            # TODO: is this really the right move? what if the user logs
            #     a non-custom chart to this key?
            if k in split_table_set:
                row[f"Custom Chart Tables/{k}_table"] = row.pop(k)
            else:
                row[f"{k}_table"] = row.pop(k)
        return row

    def _partial_history_callback(
        self,
        row: Dict[str, Any],
        step: Optional[int] = None,
        commit: Optional[bool] = None,
    ) -> None:
        row = row.copy()
        if row:
            row = self._visualization_hack(row)

        if self._backend and self._backend.interface:
            not_using_tensorboard = len(wandb.patched["tensorboard"]) == 0

            self._backend.interface.publish_partial_history(
                row,
                user_step=self._step,
                step=step,
                flush=commit,
                publish_step=not_using_tensorboard,
            )

    def _console_callback(self, name: str, data: str) -> None:
        # logger.info("console callback: %s, %s", name, data)
        if self._backend and self._backend.interface:
            self._backend.interface.publish_output(name, data)

    @_run_decorator._noop_on_finish(only_warn=True)
    def _console_raw_callback(self, name: str, data: str) -> None:
        # logger.info("console callback: %s, %s", name, data)

        # NOTE: console output is only allowed on the process which installed the callback
        # this will prevent potential corruption in the socket to the service.  Other methods
        # are protected by the _attach run decorator, but this callback was installed on the
        # write function of stdout and stderr streams.
        console_pid = getattr(self, "_attach_pid", 0)
        if console_pid != os.getpid():
            return

        if self._backend and self._backend.interface:
            self._backend.interface.publish_output_raw(name, data)

    def _tensorboard_callback(
        self, logdir: str, save: bool = True, root_logdir: str = ""
    ) -> None:
        logger.info("tensorboard callback: %s, %s", logdir, save)
        if self._backend and self._backend.interface:
            self._backend.interface.publish_tbdata(logdir, save, root_logdir)

    def _set_library(self, library: _WandbSetup) -> None:
        self._wl = library

    def _set_backend(self, backend: "wandb.sdk.backend.backend.Backend") -> None:
        self._backend = backend

    def _set_internal_run_interface(
        self,
        interface: "wandb.sdk.interface.interface_queue.InterfaceQueue",
    ) -> None:
        self._internal_run_interface = interface

    def _set_reporter(self, reporter: Reporter) -> None:
        self._reporter = reporter

    def _set_teardown_hooks(self, hooks: List[TeardownHook]) -> None:
        self._teardown_hooks = hooks

    def _set_run_obj(self, run_obj: RunRecord) -> None:
        self._run_obj = run_obj
        if self.settings._offline:
            return

        self._entity = run_obj.entity
        self._project = run_obj.project

        # Grab the config from resuming
        if run_obj.config:
            c_dict = config_util.dict_no_value_from_proto_list(run_obj.config.update)
            # TODO: Windows throws a wild error when this is set...
            if "_wandb" in c_dict:
                del c_dict["_wandb"]
            # We update the config object here without triggering the callback
            self._config._update(c_dict, allow_val_change=True, ignore_locked=True)
        # Update the summary, this will trigger an un-needed graphql request :(
        if run_obj.summary:
            summary_dict = {}
            for orig in run_obj.summary.update:
                summary_dict[orig.key] = json.loads(orig.value_json)
            if summary_dict:
                self.summary.update(summary_dict)
        self._step = self._get_starting_step()

        # update settings from run_obj
        self._settings._apply_run_start(message_to_dict(self._run_obj))
        self._update_settings(self._settings)

        wandb._sentry.configure_scope(
            process_context="user",
            tags=dict(self._settings),
        )

    def _add_singleton(
        self, data_type: str, key: str, value: Dict[Union[int, str], str]
    ) -> None:
        """Store a singleton item to wandb config.

        A singleton in this context is a piece of data that is continually
        logged with the same value in each history step, but represented
        as a single item in the config.

        We do this to avoid filling up history with a lot of repeated unnecessary data

        Add singleton can be called many times in one run, and it will only be
        updated when the value changes. The last value logged will be the one
        persisted to the server.
        """
        value_extra = {"type": data_type, "key": key, "value": value}

        if data_type not in self._config["_wandb"]:
            self._config["_wandb"][data_type] = {}

        if data_type in self._config["_wandb"][data_type]:
            old_value = self._config["_wandb"][data_type][key]
        else:
            old_value = None

        if value_extra != old_value:
            self._config["_wandb"][data_type][key] = value_extra
            self._config.persist()

    def _log(
        self,
        data: Dict[str, Any],
        step: Optional[int] = None,
        commit: Optional[bool] = None,
    ) -> None:
        if not isinstance(data, Mapping):
            raise ValueError("wandb.log must be passed a dictionary")

        if any(not isinstance(key, str) for key in data.keys()):
            raise ValueError("Key values passed to `wandb.log` must be strings.")

        self._partial_history_callback(data, step, commit)

        if step is not None:
            if os.getpid() != self._init_pid or self._is_attached:
                wandb.termwarn(
                    "Note that setting step in multiprocessing can result in data loss. "
                    "Please use `run.define_metric(...)` to define a custom metric "
                    "to log your step values.",
                    repeat=False,
                )
            # if step is passed in when tensorboard_sync is used we honor the step passed
            # to make decisions about how to close out the history record, but will strip
            # this history later on in publish_history()
            if len(wandb.patched["tensorboard"]) > 0:
                wandb.termwarn(
                    "Step cannot be set when using tensorboard syncing. "
                    "Please use `run.define_metric(...)` to define a custom metric "
                    "to log your step values.",
                    repeat=False,
                )
            if step > self._step:
                self._step = step

        if (step is None and commit is None) or commit:
            self._step += 1

    @_run_decorator._noop
    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def log(
        self,
        data: Dict[str, Any],
        step: Optional[int] = None,
        commit: Optional[bool] = None,
        sync: Optional[bool] = None,
    ) -> None:
        """Upload run data.

        Use `log` to log data from runs, such as scalars, images, video,
        histograms, plots, and tables.

        See our [guides to logging](https://docs.wandb.ai/guides/track/log) for
        live examples, code snippets, best practices, and more.

        The most basic usage is `run.log({"train-loss": 0.5, "accuracy": 0.9})`.
        This will save the loss and accuracy to the run's history and update
        the summary values for these metrics.

        Visualize logged data in the workspace at [wandb.ai](https://wandb.ai),
        or locally on a [self-hosted instance](https://docs.wandb.ai/guides/hosting)
        of the W&B app, or export data to visualize and explore locally, e.g. in
        Jupyter notebooks, with [our API](https://docs.wandb.ai/guides/track/public-api-guide).

        Logged values don't have to be scalars. Logging any wandb object is supported.
        For example `run.log({"example": wandb.Image("myimage.jpg")})` will log an
        example image which will be displayed nicely in the W&B UI.
        See the [reference documentation](https://docs.wandb.com/ref/python/data-types)
        for all of the different supported types or check out our
        [guides to logging](https://docs.wandb.ai/guides/track/log) for examples,
        from 3D molecular structures and segmentation masks to PR curves and histograms.
        You can use `wandb.Table` to log structured data. See our
        [guide to logging tables](https://docs.wandb.ai/guides/data-vis/log-tables)
        for details.

        The W&B UI organizes metrics with a forward slash (`/`) in their name
        into sections named using the text before the final slash. For example,
        the following results in two sections named "train" and "validate":

        ```
        run.log({
            "train/accuracy": 0.9,
            "train/loss": 30,
            "validate/accuracy": 0.8,
            "validate/loss": 20,
        })
        ```

        Only one level of nesting is supported; `run.log({"a/b/c": 1})`
        produces a section named "a/b".

        `run.log` is not intended to be called more than a few times per second.
        For optimal performance, limit your logging to once every N iterations,
        or collect data over multiple iterations and log it in a single step.

        ### The W&B step

        With basic usage, each call to `log` creates a new "step".
        The step must always increase, and it is not possible to log
        to a previous step.

        Note that you can use any metric as the X axis in charts.
        In many cases, it is better to treat the W&B step like
        you'd treat a timestamp rather than a training step.

        ```
        # Example: log an "epoch" metric for use as an X axis.
        run.log({"epoch": 40, "train-loss": 0.5})
        ```

        See also [define_metric](https://docs.wandb.ai/ref/python/run#define_metric).

        It is possible to use multiple `log` invocations to log to
        the same step with the `step` and `commit` parameters.
        The following are all equivalent:

        ```
        # Normal usage:
        run.log({"train-loss": 0.5, "accuracy": 0.8})
        run.log({"train-loss": 0.4, "accuracy": 0.9})

        # Implicit step without auto-incrementing:
        run.log({"train-loss": 0.5}, commit=False)
        run.log({"accuracy": 0.8})
        run.log({"train-loss": 0.4}, commit=False)
        run.log({"accuracy": 0.9})

        # Explicit step:
        run.log({"train-loss": 0.5}, step=current_step)
        run.log({"accuracy": 0.8}, step=current_step)
        current_step += 1
        run.log({"train-loss": 0.4}, step=current_step)
        run.log({"accuracy": 0.9}, step=current_step)
        ```

        Arguments:
            data: A `dict` with `str` keys and values that are serializable
                Python objects including: `int`, `float` and `string`;
                any of the `wandb.data_types`; lists, tuples and NumPy arrays
                of serializable Python objects; other `dict`s of this
                structure.
            step: The step number to log. If `None`, then an implicit
                auto-incrementing step is used. See the notes in
                the description.
            commit: If true, finalize and upload the step. If false, then
                accumulate data for the step. See the notes in the description.
                If `step` is `None`, then the default is `commit=True`;
                otherwise, the default is `commit=False`.
            sync: This argument is deprecated and does nothing.

        Examples:
            For more and more detailed examples, see
            [our guides to logging](https://docs.wandb.com/guides/track/log).

            ### Basic usage
            <!--yeadoc-test:init-and-log-basic-->
            ```python
            import wandb

            run = wandb.init()
            run.log({"accuracy": 0.9, "epoch": 5})
            ```

            ### Incremental logging
            <!--yeadoc-test:init-and-log-incremental-->
            ```python
            import wandb

            run = wandb.init()
            run.log({"loss": 0.2}, commit=False)
            # Somewhere else when I'm ready to report this step:
            run.log({"accuracy": 0.8})
            ```

            ### Histogram
            <!--yeadoc-test:init-and-log-histogram-->
            ```python
            import numpy as np
            import wandb

            # sample gradients at random from normal distribution
            gradients = np.random.randn(100, 100)
            run = wandb.init()
            run.log({"gradients": wandb.Histogram(gradients)})
            ```

            ### Image from numpy
            <!--yeadoc-test:init-and-log-image-numpy-->
            ```python
            import numpy as np
            import wandb

            run = wandb.init()
            examples = []
            for i in range(3):
                pixels = np.random.randint(low=0, high=256, size=(100, 100, 3))
                image = wandb.Image(pixels, caption=f"random field {i}")
                examples.append(image)
            run.log({"examples": examples})
            ```

            ### Image from PIL
            <!--yeadoc-test:init-and-log-image-pillow-->
            ```python
            import numpy as np
            from PIL import Image as PILImage
            import wandb

            run = wandb.init()
            examples = []
            for i in range(3):
                pixels = np.random.randint(low=0, high=256, size=(100, 100, 3), dtype=np.uint8)
                pil_image = PILImage.fromarray(pixels, mode="RGB")
                image = wandb.Image(pil_image, caption=f"random field {i}")
                examples.append(image)
            run.log({"examples": examples})
            ```

            ### Video from numpy
            <!--yeadoc-test:init-and-log-video-numpy-->
            ```python
            import numpy as np
            import wandb

            run = wandb.init()
            # axes are (time, channel, height, width)
            frames = np.random.randint(low=0, high=256, size=(10, 3, 100, 100), dtype=np.uint8)
            run.log({"video": wandb.Video(frames, fps=4)})
            ```

            ### Matplotlib Plot
            <!--yeadoc-test:init-and-log-matplotlib-->
            ```python
            from matplotlib import pyplot as plt
            import numpy as np
            import wandb

            run = wandb.init()
            fig, ax = plt.subplots()
            x = np.linspace(0, 10)
            y = x * x
            ax.plot(x, y)  # plot y = x^2
            run.log({"chart": fig})
            ```

            ### PR Curve
            ```python
            import wandb

            run = wandb.init()
            run.log({"pr": wandb.plot.pr_curve(y_test, y_probas, labels)})
            ```

            ### 3D Object
            ```python
            import wandb

            run = wandb.init()
            run.log(
                {
                    "generated_samples": [
                        wandb.Object3D(open("sample.obj")),
                        wandb.Object3D(open("sample.gltf")),
                        wandb.Object3D(open("sample.glb")),
                    ]
                }
            )
            ```

        Raises:
            wandb.Error: if called before `wandb.init`
            ValueError: if invalid data is passed

        """
        if step is not None:
            with telemetry.context(run=self) as tel:
                tel.feature.set_step_log = True

        if sync is not None:
            deprecate.deprecate(
                field_name=deprecate.Deprecated.run__log_sync,
                warning_message=(
                    "`sync` argument is deprecated and does not affect the behaviour of `wandb.log`"
                ),
            )
        if self._settings._shared and step is not None:
            wandb.termwarn(
                "In shared mode, the use of `wandb.log` with the step argument is not supported "
                f"and will be ignored. Please refer to {wburls.get('wandb_define_metric')} "
                "on how to customize your x-axis.",
                repeat=False,
            )
        self._log(data=data, step=step, commit=commit)

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def save(
        self,
        glob_str: Optional[Union[str, os.PathLike]] = None,
        base_path: Optional[Union[str, os.PathLike]] = None,
        policy: PolicyName = "live",
    ) -> Union[bool, List[str]]:
        """Sync one or more files to W&B.

        Relative paths are relative to the current working directory.

        A Unix glob, such as "myfiles/*", is expanded at the time `save` is
        called regardless of the `policy`. In particular, new files are not
        picked up automatically.

        A `base_path` may be provided to control the directory structure of
        uploaded files. It should be a prefix of `glob_str`, and the directory
        structure beneath it is preserved. It's best understood through
        examples:

        ```
        wandb.save("these/are/myfiles/*")
        # => Saves files in a "these/are/myfiles/" folder in the run.

        wandb.save("these/are/myfiles/*", base_path="these")
        # => Saves files in an "are/myfiles/" folder in the run.

        wandb.save("/User/username/Documents/run123/*.txt")
        # => Saves files in a "run123/" folder in the run. See note below.

        wandb.save("/User/username/Documents/run123/*.txt", base_path="/User")
        # => Saves files in a "username/Documents/run123/" folder in the run.

        wandb.save("files/*/saveme.txt")
        # => Saves each "saveme.txt" file in an appropriate subdirectory
        #    of "files/".
        ```

        Note: when given an absolute path or glob and no `base_path`, one
        directory level is preserved as in the example above.

        Arguments:
            glob_str: A relative or absolute path or Unix glob.
            base_path: A path to use to infer a directory structure; see examples.
            policy: One of `live`, `now`, or `end`.
                * live: upload the file as it changes, overwriting the previous version
                * now: upload the file once now
                * end: upload file when the run ends

        Returns:
            Paths to the symlinks created for the matched files.

            For historical reasons, this may return a boolean in legacy code.
        """
        if glob_str is None:
            # noop for historical reasons, run.save() may be called in legacy code
            deprecate.deprecate(
                field_name=deprecate.Deprecated.run__save_no_args,
                warning_message=(
                    "Calling wandb.run.save without any arguments is deprecated."
                    "Changes to attributes are automatically persisted."
                ),
            )
            return True

        if isinstance(glob_str, bytes):
            # Preserved for backward compatibility: allow bytes inputs.
            glob_str = glob_str.decode("utf-8")
        if isinstance(glob_str, str) and (
            glob_str.startswith("gs://") or glob_str.startswith("s3://")
        ):
            # Provide a better error message for a common misuse.
            wandb.termlog(f"{glob_str} is a cloud storage url, can't save file to W&B.")
            return []
        # NOTE: We use PurePath instead of Path because WindowsPath doesn't
        # like asterisks and errors out in resolve(). It also makes logical
        # sense: globs aren't real paths, they're just path-like strings.
        glob_path = pathlib.PurePath(glob_str)
        resolved_glob_path = pathlib.PurePath(os.path.abspath(glob_path))

        if base_path is not None:
            base_path = pathlib.Path(base_path)
        elif not glob_path.is_absolute():
            base_path = pathlib.Path(".")
        else:
            # Absolute glob paths with no base path get special handling.
            wandb.termwarn(
                "Saving files without folders. If you want to preserve "
                "subdirectories pass base_path to wandb.save, i.e. "
                'wandb.save("/mnt/folder/file.h5", base_path="/mnt")',
                repeat=False,
            )
            base_path = resolved_glob_path.parent.parent

        if policy not in ("live", "end", "now"):
            raise ValueError(
                'Only "live", "end" and "now" policies are currently supported.'
            )

        resolved_base_path = pathlib.PurePath(os.path.abspath(base_path))

        return self._save(
            resolved_glob_path,
            resolved_base_path,
            policy,
        )

    def _save(
        self,
        glob_path: pathlib.PurePath,
        base_path: pathlib.PurePath,
        policy: "PolicyName",
    ) -> List[str]:
        # Can't use is_relative_to() because that's added in Python 3.9,
        # but we support down to Python 3.7.
        if not str(glob_path).startswith(str(base_path)):
            raise ValueError("Glob may not walk above the base path")

        if glob_path == base_path:
            raise ValueError("Glob cannot be the same as the base path")

        relative_glob = glob_path.relative_to(base_path)
        if relative_glob.parts[0] == "*":
            raise ValueError("Glob may not start with '*' relative to the base path")
        relative_glob_str = GlobStr(str(relative_glob))

        with telemetry.context(run=self) as tel:
            tel.feature.save = True

        # Files in the files directory matched by the glob, including old and
        # new ones.
        globbed_files = set(
            pathlib.Path(
                self._settings.files_dir,
            ).glob(relative_glob_str)
        )

        had_symlinked_files = len(globbed_files) > 0
        is_star_glob = "*" in relative_glob_str

        # The base_path may itself be a glob, so we can't do
        #     base_path.glob(relative_glob_str)
        for path_str in glob.glob(str(base_path / relative_glob_str)):
            source_path = pathlib.Path(path_str).absolute()

            # We can't use relative_to() because base_path may be a glob.
            relative_path = pathlib.Path(*source_path.parts[len(base_path.parts) :])

            target_path = pathlib.Path(self._settings.files_dir, relative_path)
            globbed_files.add(target_path)

            # If the file is already where it needs to be, don't create a symlink.
            if source_path.resolve() == target_path.resolve():
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Delete the symlink if it exists.
            try:
                target_path.unlink()
            except FileNotFoundError:
                # In Python 3.8, we would pass missing_ok=True, but as of now
                # we support down to Python 3.7.
                pass

            target_path.symlink_to(source_path)

        # Inform users that new files aren't detected automatically.
        if not had_symlinked_files and is_star_glob:
            file_str = f"{len(globbed_files)} file"
            if len(globbed_files) > 1:
                file_str += "s"
            wandb.termwarn(
                f"Symlinked {file_str} into the W&B run directory, "
                "call wandb.save again to sync new files."
            )

        files_dict: FilesDict = {
            "files": [
                (
                    GlobStr(str(f.relative_to(self._settings.files_dir))),
                    policy,
                )
                for f in globbed_files
            ]
        }
        if self._backend and self._backend.interface:
            self._backend.interface.publish_files(files_dict)

        return [str(f) for f in globbed_files]

    @_run_decorator._attach
    def restore(
        self,
        name: str,
        run_path: Optional[str] = None,
        replace: bool = False,
        root: Optional[str] = None,
    ) -> Union[None, TextIO]:
        return restore(
            name,
            run_path or self._get_path(),
            replace,
            root or self._settings.files_dir,
        )

    @_run_decorator._noop
    @_run_decorator._attach
    def finish(
        self, exit_code: Optional[int] = None, quiet: Optional[bool] = None
    ) -> None:
        """Mark a run as finished, and finish uploading all data.

        This is used when creating multiple runs in the same process. We automatically
        call this method when your script exits or if you use the run context manager.

        Arguments:
            exit_code: Set to something other than 0 to mark a run as failed
            quiet: Set to true to minimize log output
        """
        return self._finish(exit_code, quiet)

    def _finish(
        self,
        exit_code: Optional[int] = None,
        quiet: Optional[bool] = None,
    ) -> None:
        logger.info(f"finishing run {self._get_path()}")
        with telemetry.context(run=self) as tel:
            tel.feature.finish = True

        if quiet is not None:
            self._quiet = quiet

        # Pop this run (hopefully) from the run stack, to support the "reinit"
        # functionality of wandb.init().
        #
        # TODO: It's not clear how _global_run_stack could have length other
        # than 1 at this point in the code. If you're reading this, consider
        # refactoring this thing.
        if self._wl and len(self._wl._global_run_stack) > 0:
            self._wl._global_run_stack.pop()

        # Run hooks that need to happen before the last messages to the
        # internal service, like Jupyter hooks.
        for hook in self._teardown_hooks:
            if hook.stage == TeardownStage.EARLY:
                hook.call()

        # Early-stage hooks may use methods that require _is_finished
        # to be False, so we set this after running those hooks.
        self._is_finished = True

        try:
            self._atexit_cleanup(exit_code=exit_code)

            # Run hooks that should happen after the last messages to the
            # internal service, like detaching the logger.
            for hook in self._teardown_hooks:
                if hook.stage == TeardownStage.LATE:
                    hook.call()
            self._teardown_hooks = []

            # Inform the service that we're done sending messages for this run.
            #
            # TODO: Why not do this in _atexit_cleanup()?
            service = self._wl and self._wl.service
            if service:
                service.inform_finish(run_id=self._run_id)

        finally:
            module.unset_globals()
            wandb._sentry.end_session()

    @_run_decorator._noop
    @_run_decorator._attach
    def join(self, exit_code: Optional[int] = None) -> None:
        """Deprecated alias for `finish()` - use finish instead."""
        if hasattr(self, "_telemetry_obj"):
            deprecate.deprecate(
                field_name=deprecate.Deprecated.run__join,
                warning_message=(
                    "wandb.run.join() is deprecated, please use wandb.run.finish()."
                ),
            )
        self._finish(exit_code=exit_code)

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def status(
        self,
    ) -> RunStatus:
        """Get sync info from the internal backend, about the current run's sync status."""
        if not self._backend or not self._backend.interface:
            return RunStatus()

        handle_run_status = self._backend.interface.deliver_request_run_status()
        result = handle_run_status.wait(timeout=-1)
        assert result
        sync_data = result.response.run_status_response

        sync_time = None
        if sync_data.sync_time.seconds:
            sync_time = datetime.fromtimestamp(
                sync_data.sync_time.seconds + sync_data.sync_time.nanos / 1e9
            )
        return RunStatus(
            sync_items_total=sync_data.sync_items_total,
            sync_items_pending=sync_data.sync_items_pending,
            sync_time=sync_time,
        )

    @staticmethod
    def plot_table(
        vega_spec_name: str,
        data_table: "wandb.Table",
        fields: Dict[str, Any],
        string_fields: Optional[Dict[str, Any]] = None,
        split_table: Optional[bool] = False,
    ) -> CustomChart:
        """Create a custom plot on a table.

        Arguments:
            vega_spec_name: the name of the spec for the plot
            data_table: a wandb.Table object containing the data to
                be used on the visualization
            fields: a dict mapping from table keys to fields that the custom
                visualization needs
            string_fields: a dict that provides values for any string constants
                the custom visualization needs
        """
        return custom_chart(
            vega_spec_name, data_table, fields, string_fields or {}, split_table
        )

    def _add_panel(
        self, visualize_key: str, panel_type: str, panel_config: dict
    ) -> None:
        config = {
            "panel_type": panel_type,
            "panel_config": panel_config,
        }
        self._config_callback(val=config, key=("_wandb", "visualize", visualize_key))

    def _set_globals(self) -> None:
        module.set_global(
            run=self,
            config=self.config,
            log=self.log,
            summary=self.summary,
            save=self.save,
            use_artifact=self.use_artifact,
            log_artifact=self.log_artifact,
            define_metric=self.define_metric,
            plot_table=self.plot_table,
            alert=self.alert,
            mark_preempting=self.mark_preempting,
            log_model=self.log_model,
            use_model=self.use_model,
            link_model=self.link_model,
        )

    def _redirect(
        self,
        stdout_slave_fd: Optional[int],
        stderr_slave_fd: Optional[int],
        console: Optional[str] = None,
    ) -> None:
        if console is None:
            console = self._settings.console
        # only use raw for service to minimize potential changes
        if console == "wrap":
            if not self._settings._disable_service:
                console = "wrap_raw"
            else:
                console = "wrap_emu"
        logger.info("redirect: %s", console)

        out_redir: redirect.RedirectBase
        err_redir: redirect.RedirectBase

        # raw output handles the output_log writing in the internal process
        if console in {"redirect", "wrap_emu"}:
            output_log_path = os.path.join(
                self._settings.files_dir, filenames.OUTPUT_FNAME
            )
            # output writer might have been set up, see wrap_fallback case
            if not self._output_writer:
                self._output_writer = filesystem.CRDedupedFile(
                    open(output_log_path, "wb")
                )

        if console == "redirect":
            logger.info("Redirecting console.")
            out_redir = redirect.Redirect(
                src="stdout",
                cbs=[
                    lambda data: self._console_callback("stdout", data),
                    self._output_writer.write,  # type: ignore
                ],
            )
            err_redir = redirect.Redirect(
                src="stderr",
                cbs=[
                    lambda data: self._console_callback("stderr", data),
                    self._output_writer.write,  # type: ignore
                ],
            )
            if os.name == "nt":

                def wrap_fallback() -> None:
                    if self._out_redir:
                        self._out_redir.uninstall()
                    if self._err_redir:
                        self._err_redir.uninstall()
                    msg = (
                        "Tensorflow detected. Stream redirection is not supported "
                        "on Windows when tensorflow is imported. Falling back to "
                        "wrapping stdout/err."
                    )
                    wandb.termlog(msg)
                    self._redirect(None, None, console="wrap")

                add_import_hook("tensorflow", wrap_fallback)
        elif console == "wrap_emu":
            logger.info("Wrapping output streams.")
            out_redir = redirect.StreamWrapper(
                src="stdout",
                cbs=[
                    lambda data: self._console_callback("stdout", data),
                    self._output_writer.write,  # type: ignore
                ],
            )
            err_redir = redirect.StreamWrapper(
                src="stderr",
                cbs=[
                    lambda data: self._console_callback("stderr", data),
                    self._output_writer.write,  # type: ignore
                ],
            )
        elif console == "wrap_raw":
            logger.info("Wrapping output streams.")
            out_redir = redirect.StreamRawWrapper(
                src="stdout",
                cbs=[
                    lambda data: self._console_raw_callback("stdout", data),
                ],
            )
            err_redir = redirect.StreamRawWrapper(
                src="stderr",
                cbs=[
                    lambda data: self._console_raw_callback("stderr", data),
                ],
            )
        elif console == "off":
            return
        else:
            raise ValueError("unhandled console")
        try:
            # save stdout and stderr before installing new write functions
            out_redir.save()
            err_redir.save()
            out_redir.install()
            err_redir.install()
            self._out_redir = out_redir
            self._err_redir = err_redir
            logger.info("Redirects installed.")
        except Exception as e:
            print(e)
            logger.error("Failed to redirect.", exc_info=e)
        return

    def _restore(self) -> None:
        logger.info("restore")
        # TODO(jhr): drain and shutdown all threads
        if self._out_redir:
            self._out_redir.uninstall()
        if self._err_redir:
            self._err_redir.uninstall()
        logger.info("restore done")

    def _atexit_cleanup(self, exit_code: Optional[int] = None) -> None:
        if self._backend is None:
            logger.warning("process exited without backend configured")
            return
        if self._atexit_cleanup_called:
            return
        self._atexit_cleanup_called = True

        exit_code = exit_code or (self._hooks and self._hooks.exit_code) or 0
        self._exit_code = exit_code
        logger.info(f"got exitcode: {exit_code}")

        # Delete this run's "resume" file if the run finished successfully.
        #
        # This is used by the "auto" resume mode, which resumes from the last
        # failed (or unfinished/crashed) run. If we reach this line, then this
        # run shouldn't be a candidate for "auto" resume.
        if exit_code == 0:
            if os.path.exists(self._settings.resume_fname):
                os.remove(self._settings.resume_fname)

        try:
            self._on_finish()

        except KeyboardInterrupt:
            if not wandb.wandb_agent._is_running():  # type: ignore
                wandb.termerror("Control-C detected -- Run data was not synced")
            raise

        except Exception as e:
            self._console_stop()
            logger.error("Problem finishing run", exc_info=e)
            wandb.termerror("Problem finishing run")
            raise

        Run._footer(
            sampled_history=self._sampled_history,
            final_summary=self._final_summary,
            poll_exit_response=self._poll_exit_response,
            internal_messages_response=self._internal_messages_response,
            reporter=self._reporter,
            quiet=self._quiet,
            settings=self._settings,
            printer=self._printer,
        )

    def _console_start(self) -> None:
        logger.info("atexit reg")
        self._hooks = ExitHooks()

        service = self._wl and self._wl.service
        if not service:
            self._hooks.hook()
            # NB: manager will perform atexit hook like behavior for outstanding runs
            atexit.register(lambda: self._atexit_cleanup())

        self._redirect(self._stdout_slave_fd, self._stderr_slave_fd)

    def _console_stop(self) -> None:
        self._restore()
        if self._output_writer:
            self._output_writer.close()
            self._output_writer = None

    def _on_init(self) -> None:
        if self._settings._offline:
            return

    def _on_start(self) -> None:
        # would like to move _set_global to _on_ready to unify _on_start and _on_attach
        # (we want to do the set globals after attach)
        # TODO(console) However _console_start calls Redirect that uses `wandb.run` hence breaks
        # TODO(jupyter) However _header calls _header_run_info that uses wandb.jupyter that uses
        #               `wandb.run` and hence breaks
        self._set_globals()
        self._header(settings=self._settings, printer=self._printer)

        if self._settings.save_code and self._settings.code_dir is not None:
            self.log_code(self._settings.code_dir)

        if self._settings._save_requirements:
            if self._backend and self._backend.interface:
                from wandb.util import working_set

                logger.debug(
                    "Saving list of pip packages installed into the current environment"
                )
                self._backend.interface.publish_python_packages(working_set())

        if self._backend and self._backend.interface and not self._settings._offline:
            self._run_status_checker = RunStatusChecker(
                interface=self._backend.interface,
            )
            self._run_status_checker.start()

        self._console_start()
        self._on_ready()

    def _on_attach(self) -> None:
        """Event triggered when run is attached to another run."""
        with telemetry.context(run=self) as tel:
            tel.feature.attach = True

        self._set_globals()
        self._is_attached = True
        self._on_ready()

    def _register_telemetry_import_hooks(
        self,
    ) -> None:
        def _telemetry_import_hook(
            run: "Run",
            module: Any,
        ) -> None:
            with telemetry.context(run=run) as tel:
                try:
                    name = getattr(module, "__name__", None)
                    if name is not None:
                        setattr(tel.imports_finish, name, True)
                except AttributeError:
                    return

        import_telemetry_set = telemetry.list_telemetry_imports()
        import_hook_fn = functools.partial(_telemetry_import_hook, self)
        for module_name in import_telemetry_set:
            register_post_import_hook(
                import_hook_fn,
                self._run_id,
                module_name,
            )

    def _on_ready(self) -> None:
        """Event triggered when run is ready for the user."""
        self._register_telemetry_import_hooks()

        # start reporting any telemetry changes
        self._telemetry_obj_active = True
        self._telemetry_flush()

        self._detect_and_apply_job_inputs()

        # object is about to be returned to the user, don't let them modify it
        self._freeze()

        if not self._settings.resume:
            if os.path.exists(self._settings.resume_fname):
                os.remove(self._settings.resume_fname)

    def _detect_and_apply_job_inputs(self) -> None:
        """If the user has staged launch inputs, apply them to the run."""
        from wandb.sdk.launch.inputs.internal import StagedLaunchInputs

        StagedLaunchInputs().apply(self)

    def _make_job_source_reqs(self) -> Tuple[List[str], Dict[str, Any], Dict[str, Any]]:
        from wandb.util import working_set

        installed_packages_list = sorted(f"{d.key}=={d.version}" for d in working_set())
        input_types = TypeRegistry.type_of(self.config.as_dict()).to_json()
        output_types = TypeRegistry.type_of(self.summary._as_dict()).to_json()

        return installed_packages_list, input_types, output_types

    def _construct_job_artifact(
        self,
        name: str,
        source_dict: "JobSourceDict",
        installed_packages_list: List[str],
        patch_path: Optional[os.PathLike] = None,
    ) -> "Artifact":
        job_artifact = job_builder.JobArtifact(name)
        if patch_path and os.path.exists(patch_path):
            job_artifact.add_file(FilePathStr(str(patch_path)), "diff.patch")
        with job_artifact.new_file("requirements.frozen.txt") as f:
            f.write("\n".join(installed_packages_list))
        with job_artifact.new_file("wandb-job.json") as f:
            f.write(json.dumps(source_dict))

        return job_artifact

    def _create_image_job(
        self,
        input_types: Dict[str, Any],
        output_types: Dict[str, Any],
        installed_packages_list: List[str],
        docker_image_name: Optional[str] = None,
        args: Optional[List[str]] = None,
    ) -> Optional["Artifact"]:
        docker_image_name = docker_image_name or os.getenv("WANDB_DOCKER")

        if not docker_image_name:
            return None

        name = wandb.util.make_artifact_name_safe(f"job-{docker_image_name}")
        s_args: Sequence[str] = args if args is not None else self._settings._args
        source_info: JobSourceDict = {
            "_version": "v0",
            "source_type": "image",
            "source": {"image": docker_image_name, "args": s_args},
            "input_types": input_types,
            "output_types": output_types,
            "runtime": self._settings._python,
        }
        job_artifact = self._construct_job_artifact(
            name, source_info, installed_packages_list
        )

        return job_artifact

    def _log_job_artifact_with_image(
        self, docker_image_name: str, args: Optional[List[str]] = None
    ) -> Artifact:
        packages, in_types, out_types = self._make_job_source_reqs()
        job_artifact = self._create_image_job(
            in_types,
            out_types,
            packages,
            args=args,
            docker_image_name=docker_image_name,
        )

        artifact = self.log_artifact(job_artifact)

        if not artifact:
            raise wandb.Error(f"Job Artifact log unsuccessful: {artifact}")
        else:
            return artifact

    def _on_probe_exit(self, probe_handle: MailboxProbe) -> None:
        handle = probe_handle.get_mailbox_handle()
        if handle:
            result = handle.wait(timeout=0, release=False)
            if not result:
                return
            probe_handle.set_probe_result(result)
        assert self._backend and self._backend.interface
        handle = self._backend.interface.deliver_poll_exit()
        probe_handle.set_mailbox_handle(handle)

    def _on_progress_exit(self, progress_handle: MailboxProgress) -> None:
        probe_handles = progress_handle.get_probe_handles()
        assert probe_handles and len(probe_handles) == 1

        result = probe_handles[0].get_probe_result()
        if not result:
            return
        self._footer_file_pusher_status_info(
            result.response.poll_exit_response, printer=self._printer
        )

    def _on_finish(self) -> None:
        trigger.call("on_finished")

        if self._run_status_checker is not None:
            self._run_status_checker.stop()

        self._console_stop()  # TODO: there's a race here with jupyter console logging

        assert self._backend and self._backend.interface

        exit_handle = self._backend.interface.deliver_exit(self._exit_code)
        exit_handle.add_probe(on_probe=self._on_probe_exit)

        # wait for the exit to complete
        _ = exit_handle.wait(timeout=-1, on_progress=self._on_progress_exit)

        poll_exit_handle = self._backend.interface.deliver_poll_exit()
        # wait for them, it's ok to do this serially but this can be improved
        result = poll_exit_handle.wait(timeout=-1)
        assert result
        self._footer_file_pusher_status_info(
            result.response.poll_exit_response, printer=self._printer
        )
        self._poll_exit_response = result.response.poll_exit_response
        internal_messages_handle = self._backend.interface.deliver_internal_messages()
        result = internal_messages_handle.wait(timeout=-1)
        assert result
        self._internal_messages_response = result.response.internal_messages_response

        # dispatch all our final requests

        final_summary_handle = self._backend.interface.deliver_get_summary()
        sampled_history_handle = (
            self._backend.interface.deliver_request_sampled_history()
        )

        result = sampled_history_handle.wait(timeout=-1)
        assert result
        self._sampled_history = result.response.sampled_history_response

        result = final_summary_handle.wait(timeout=-1)
        assert result
        self._final_summary = result.response.get_summary_response

        if self._backend:
            self._backend.cleanup()

        if self._run_status_checker:
            self._run_status_checker.join()

        self._unregister_telemetry_import_hooks(self._run_id)

    @staticmethod
    def _unregister_telemetry_import_hooks(run_id: str) -> None:
        import_telemetry_set = telemetry.list_telemetry_imports()
        for module_name in import_telemetry_set:
            unregister_post_import_hook(module_name, run_id)

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def define_metric(
        self,
        name: str,
        step_metric: Union[str, wandb_metric.Metric, None] = None,
        step_sync: Optional[bool] = None,
        hidden: Optional[bool] = None,
        summary: Optional[str] = None,
        goal: Optional[str] = None,
        overwrite: Optional[bool] = None,
    ) -> wandb_metric.Metric:
        """Customize metrics logged with `wandb.log()`.

        Arguments:
            name: The name of the metric to customize.
            step_metric: The name of another metric to serve as the X-axis
                for this metric in automatically generated charts.
            step_sync: Automatically insert the last value of step_metric into
                `run.log()` if it is not provided explicitly. Defaults to True
                 if step_metric is specified.
            hidden: Hide this metric from automatic plots.
            summary: Specify aggregate metrics added to summary.
                Supported aggregations include "min", "max", "mean", "last",
                "best", "copy" and "none". "best" is used together with the
                goal parameter. "none" prevents a summary from being generated.
                "copy" is deprecated and should not be used.
            goal: Specify how to interpret the "best" summary type.
                Supported options are "minimize" and "maximize".
            overwrite: If false, then this call is merged with previous
                `define_metric` calls for the same metric by using their
                values for any unspecified parameters. If true, then
                unspecified parameters overwrite values specified by
                previous calls.

        Returns:
            An object that represents this call but can otherwise be discarded.
        """
        if summary and "copy" in summary:
            deprecate.deprecate(
                deprecate.Deprecated.run__define_metric_copy,
                "define_metric(summary='copy') is deprecated and will be removed.",
                self,
            )

        if (summary and "best" in summary) or goal is not None:
            deprecate.deprecate(
                deprecate.Deprecated.run__define_metric_best_goal,
                "define_metric(summary='best', goal=...) is deprecated and will be removed. "
                "Use define_metric(summary='min') or define_metric(summary='max') instead.",
                self,
            )

        return self._define_metric(
            name,
            step_metric,
            step_sync,
            hidden,
            summary,
            goal,
            overwrite,
        )

    def _define_metric(
        self,
        name: str,
        step_metric: Union[str, wandb_metric.Metric, None] = None,
        step_sync: Optional[bool] = None,
        hidden: Optional[bool] = None,
        summary: Optional[str] = None,
        goal: Optional[str] = None,
        overwrite: Optional[bool] = None,
    ) -> wandb_metric.Metric:
        if not name:
            raise wandb.Error("define_metric() requires non-empty name argument")
        if isinstance(step_metric, wandb_metric.Metric):
            step_metric = step_metric.name
        for arg_name, arg_val, exp_type in (
            ("name", name, str),
            ("step_metric", step_metric, str),
            ("step_sync", step_sync, bool),
            ("hidden", hidden, bool),
            ("summary", summary, str),
            ("goal", goal, str),
            ("overwrite", overwrite, bool),
        ):
            # NOTE: type checking is broken for isinstance and str
            if arg_val is not None and not isinstance(arg_val, exp_type):
                arg_type = type(arg_val).__name__
                raise wandb.Error(
                    f"Unhandled define_metric() arg: {arg_name} type: {arg_type}"
                )
        stripped = name[:-1] if name.endswith("*") else name
        if "*" in stripped:
            raise wandb.Error(
                f"Unhandled define_metric() arg: name (glob suffixes only): {name}"
            )
        summary_ops: Optional[Sequence[str]] = None
        if summary:
            summary_items = [s.lower() for s in summary.split(",")]
            summary_ops = []
            valid = {"min", "max", "mean", "best", "last", "copy", "none"}
            # TODO: deprecate copy and best
            for i in summary_items:
                if i not in valid:
                    raise wandb.Error(f"Unhandled define_metric() arg: summary op: {i}")
                summary_ops.append(i)
            with telemetry.context(run=self) as tel:
                tel.feature.metric_summary = True
        # TODO: deprecate goal
        goal_cleaned: Optional[str] = None
        if goal is not None:
            goal_cleaned = goal[:3].lower()
            valid_goal = {"min", "max"}
            if goal_cleaned not in valid_goal:
                raise wandb.Error(f"Unhandled define_metric() arg: goal: {goal}")
            with telemetry.context(run=self) as tel:
                tel.feature.metric_goal = True
        if hidden:
            with telemetry.context(run=self) as tel:
                tel.feature.metric_hidden = True
        if step_sync:
            with telemetry.context(run=self) as tel:
                tel.feature.metric_step_sync = True

        with telemetry.context(run=self) as tel:
            tel.feature.metric = True

        m = wandb_metric.Metric(
            name=name,
            step_metric=step_metric,
            step_sync=step_sync,
            summary=summary_ops,
            hidden=hidden,
            goal=goal_cleaned,
            overwrite=overwrite,
        )
        m._set_callback(self._metric_callback)
        m._commit()
        return m

    # TODO(jhr): annotate this
    @_run_decorator._attach
    def watch(  # type: ignore
        self,
        models,
        criterion=None,
        log="gradients",
        log_freq=100,
        idx=None,
        log_graph=False,
    ) -> None:
        wandb.watch(models, criterion, log, log_freq, idx, log_graph)  # type: ignore

    # TODO(jhr): annotate this
    @_run_decorator._attach
    def unwatch(self, models=None) -> None:  # type: ignore
        wandb.unwatch(models=models)  # type: ignore

    # TODO(kdg): remove all artifact swapping logic
    def _swap_artifact_name(self, artifact_name: str, use_as: Optional[str]) -> str:
        artifact_key_string = use_as or artifact_name
        replacement_artifact_info = self._launch_artifact_mapping.get(
            artifact_key_string
        )
        if replacement_artifact_info is not None:
            new_name = replacement_artifact_info.get("name")
            entity = replacement_artifact_info.get("entity")
            project = replacement_artifact_info.get("project")
            if new_name is None or entity is None or project is None:
                raise ValueError(
                    "Misconfigured artifact in launch config. Must include name, project and entity keys."
                )
            return f"{entity}/{project}/{new_name}"
        elif replacement_artifact_info is None and use_as is None:
            sequence_name = artifact_name.split(":")[0].split("/")[-1]
            unique_artifact_replacement_info = (
                self._unique_launch_artifact_sequence_names.get(sequence_name)
            )
            if unique_artifact_replacement_info is not None:
                new_name = unique_artifact_replacement_info.get("name")
                entity = unique_artifact_replacement_info.get("entity")
                project = unique_artifact_replacement_info.get("project")
                if new_name is None or entity is None or project is None:
                    raise ValueError(
                        "Misconfigured artifact in launch config. Must include name, project and entity keys."
                    )
                return f"{entity}/{project}/{new_name}"

        else:
            return artifact_name

        return artifact_name

    def _detach(self) -> None:
        pass

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def link_artifact(
        self,
        artifact: Artifact,
        target_path: str,
        aliases: Optional[List[str]] = None,
    ) -> None:
        """Link the given artifact to a portfolio (a promoted collection of artifacts).

        The linked artifact will be visible in the UI for the specified portfolio.

        Arguments:
            artifact: the (public or local) artifact which will be linked
            target_path: `str` - takes the following forms: {portfolio}, {project}/{portfolio},
                or {entity}/{project}/{portfolio}
            aliases: `List[str]` - optional alias(es) that will only be applied on this linked artifact
                                   inside the portfolio.
            The alias "latest" will always be applied to the latest version of an artifact that is linked.

        Returns:
            None

        """
        portfolio, project, entity = wandb.util._parse_entity_project_item(target_path)
        if aliases is None:
            aliases = []

        if not self._backend or not self._backend.interface:
            return

        if artifact.is_draft() and not artifact._is_draft_save_started():
            artifact = self._log_artifact(artifact)

        if self._settings._offline:
            # TODO: implement offline mode + sync
            raise NotImplementedError

        # Wait until the artifact is committed before trying to link it.
        artifact.wait()

        handle = self._backend.interface.deliver_link_artifact(
            self,
            artifact,
            portfolio,
            aliases,
            entity,
            project,
        )
        if artifact._ttl_duration_seconds is not None:
            wandb.termwarn(
                "Artifact TTL will be disabled for source artifacts that are linked to portfolios."
            )
        result = handle.wait(timeout=-1)
        if result is None:
            handle.abandon()
        else:
            response = result.response.link_artifact_response
            if response.error_message:
                wandb.termerror(response.error_message)

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def use_artifact(
        self,
        artifact_or_name: Union[str, Artifact],
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        use_as: Optional[str] = None,
    ) -> Artifact:
        """Declare an artifact as an input to a run.

        Call `download` or `file` on the returned object to get the contents locally.

        Arguments:
            artifact_or_name: (str or Artifact) An artifact name.
                May be prefixed with entity/project/. Valid names
                can be in the following forms:
                    - name:version
                    - name:alias
                You can also pass an Artifact object created by calling `wandb.Artifact`
            type: (str, optional) The type of artifact to use.
            aliases: (list, optional) Aliases to apply to this artifact
            use_as: (string, optional) Optional string indicating what purpose the artifact was used with.
                                       Will be shown in UI.

        Returns:
            An `Artifact` object.
        """
        if self._settings._offline:
            raise TypeError("Cannot use artifact when in offline mode.")
        r = self._run_obj
        assert r is not None
        api = internal.Api(default_settings={"entity": r.entity, "project": r.project})
        api.set_current_run_id(self._run_id)

        if isinstance(artifact_or_name, str):
            if self._launch_artifact_mapping:
                name = self._swap_artifact_name(artifact_or_name, use_as)
            else:
                name = artifact_or_name
            public_api = self._public_api()
            artifact = public_api.artifact(type=type, name=name)
            if type is not None and type != artifact.type:
                raise ValueError(
                    "Supplied type {} does not match type {} of artifact {}".format(
                        type, artifact.type, artifact.name
                    )
                )
            artifact._use_as = use_as or artifact_or_name
            if use_as:
                if (
                    use_as in self._used_artifact_slots.keys()
                    and self._used_artifact_slots[use_as] != artifact.id
                ):
                    raise ValueError(
                        "Cannot call use_artifact with the same use_as argument more than once"
                    )
                elif ":" in use_as or "/" in use_as:
                    raise ValueError(
                        "use_as cannot contain special characters ':' or '/'"
                    )
                self._used_artifact_slots[use_as] = artifact.id
            api.use_artifact(
                artifact.id,
                entity_name=r.entity,
                project_name=r.project,
                use_as=use_as or artifact_or_name,
            )
        else:
            artifact = artifact_or_name
            if aliases is None:
                aliases = []
            elif isinstance(aliases, str):
                aliases = [aliases]
            if isinstance(artifact_or_name, Artifact) and artifact.is_draft():
                if use_as is not None:
                    wandb.termwarn(
                        "Indicating use_as is not supported when using a draft artifact"
                    )
                self._log_artifact(
                    artifact,
                    aliases=aliases,
                    is_user_created=True,
                    use_after_commit=True,
                )
                artifact.wait()
                artifact._use_as = use_as or artifact.name
            elif isinstance(artifact, Artifact) and not artifact.is_draft():
                if (
                    self._launch_artifact_mapping
                    and artifact.name in self._launch_artifact_mapping.keys()
                ):
                    wandb.termwarn(
                        "Swapping artifacts is not supported when using a non-draft artifact. "
                        f"Using {artifact.name}."
                    )
                artifact._use_as = use_as or artifact.name
                api.use_artifact(
                    artifact.id, use_as=use_as or artifact._use_as or artifact.name
                )
            else:
                raise ValueError(
                    'You must pass an artifact name (e.g. "pedestrian-dataset:v1"), '
                    "an instance of `wandb.Artifact`, or `wandb.Api().artifact()` to `use_artifact`"
                )
        if self._backend and self._backend.interface:
            self._backend.interface.publish_use_artifact(artifact)
        return artifact

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def log_artifact(
        self,
        artifact_or_path: Union[Artifact, StrPath],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> Artifact:
        """Declare an artifact as an output of a run.

        Arguments:
            artifact_or_path: (str or Artifact) A path to the contents of this artifact,
                can be in the following forms:
                    - `/local/directory`
                    - `/local/directory/file.txt`
                    - `s3://bucket/path`
                You can also pass an Artifact object created by calling
                `wandb.Artifact`.
            name: (str, optional) An artifact name. Valid names can be in the following forms:
                    - name:version
                    - name:alias
                    - digest
                This will default to the basename of the path prepended with the current
                run id  if not specified.
            type: (str) The type of artifact to log, examples include `dataset`, `model`
            aliases: (list, optional) Aliases to apply to this artifact,
                defaults to `["latest"]`
            tags: (list, optional) Tags to apply to this artifact, if any.

        Returns:
            An `Artifact` object.
        """
        return self._log_artifact(
            artifact_or_path,
            name=name,
            type=type,
            aliases=aliases,
            tags=tags,
        )

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def upsert_artifact(
        self,
        artifact_or_path: Union[Artifact, str],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        distributed_id: Optional[str] = None,
    ) -> Artifact:
        """Declare (or append to) a non-finalized artifact as output of a run.

        Note that you must call run.finish_artifact() to finalize the artifact.
        This is useful when distributed jobs need to all contribute to the same artifact.

        Arguments:
            artifact_or_path: (str or Artifact) A path to the contents of this artifact,
                can be in the following forms:
                    - `/local/directory`
                    - `/local/directory/file.txt`
                    - `s3://bucket/path`
                You can also pass an Artifact object created by calling
                `wandb.Artifact`.
            name: (str, optional) An artifact name. May be prefixed with entity/project.
                Valid names can be in the following forms:
                    - name:version
                    - name:alias
                    - digest
                This will default to the basename of the path prepended with the current
                run id  if not specified.
            type: (str) The type of artifact to log, examples include `dataset`, `model`
            aliases: (list, optional) Aliases to apply to this artifact,
                defaults to `["latest"]`
            distributed_id: (string, optional) Unique string that all distributed jobs share. If None,
                defaults to the run's group name.

        Returns:
            An `Artifact` object.
        """
        if self._get_group() == "" and distributed_id is None:
            raise TypeError(
                "Cannot upsert artifact unless run is in a group or distributed_id is provided"
            )
        if distributed_id is None:
            distributed_id = self._get_group()
        return self._log_artifact(
            artifact_or_path,
            name=name,
            type=type,
            aliases=aliases,
            distributed_id=distributed_id,
            finalize=False,
        )

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def finish_artifact(
        self,
        artifact_or_path: Union[Artifact, str],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        distributed_id: Optional[str] = None,
    ) -> Artifact:
        """Finishes a non-finalized artifact as output of a run.

        Subsequent "upserts" with the same distributed ID will result in a new version.

        Arguments:
            artifact_or_path: (str or Artifact) A path to the contents of this artifact,
                can be in the following forms:
                    - `/local/directory`
                    - `/local/directory/file.txt`
                    - `s3://bucket/path`
                You can also pass an Artifact object created by calling
                `wandb.Artifact`.
            name: (str, optional) An artifact name. May be prefixed with entity/project.
                Valid names can be in the following forms:
                    - name:version
                    - name:alias
                    - digest
                This will default to the basename of the path prepended with the current
                run id  if not specified.
            type: (str) The type of artifact to log, examples include `dataset`, `model`
            aliases: (list, optional) Aliases to apply to this artifact,
                defaults to `["latest"]`
            distributed_id: (string, optional) Unique string that all distributed jobs share. If None,
                defaults to the run's group name.

        Returns:
            An `Artifact` object.
        """
        if self._get_group() == "" and distributed_id is None:
            raise TypeError(
                "Cannot finish artifact unless run is in a group or distributed_id is provided"
            )
        if distributed_id is None:
            distributed_id = self._get_group()

        return self._log_artifact(
            artifact_or_path,
            name,
            type,
            aliases,
            distributed_id=distributed_id,
            finalize=True,
        )

    def _log_artifact(
        self,
        artifact_or_path: Union[Artifact, StrPath],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        distributed_id: Optional[str] = None,
        finalize: bool = True,
        is_user_created: bool = False,
        use_after_commit: bool = False,
    ) -> Artifact:
        api = internal.Api()
        if api.settings().get("anonymous") == "true":
            wandb.termwarn(
                "Artifacts logged anonymously cannot be claimed and expire after 7 days."
            )

        if not finalize and distributed_id is None:
            raise TypeError("Must provide distributed_id if artifact is not finalize")

        if aliases is not None:
            aliases = validate_aliases(aliases)

        # Check if artifact tags are supported
        if tags is not None:
            tags = validate_tags(tags)

        artifact, aliases = self._prepare_artifact(
            artifact_or_path, name, type, aliases
        )
        artifact.distributed_id = distributed_id
        self._assert_can_log_artifact(artifact)
        if self._backend and self._backend.interface:
            if not self._settings._offline:
                future = self._backend.interface.communicate_artifact(
                    self,
                    artifact,
                    aliases,
                    tags,
                    self.step,
                    finalize=finalize,
                    is_user_created=is_user_created,
                    use_after_commit=use_after_commit,
                )
                artifact._set_save_future(future, self._public_api().client)
            else:
                self._backend.interface.publish_artifact(
                    self,
                    artifact,
                    aliases,
                    tags,
                    finalize=finalize,
                    is_user_created=is_user_created,
                    use_after_commit=use_after_commit,
                )
        elif self._internal_run_interface:
            self._internal_run_interface.publish_artifact(
                self,
                artifact,
                aliases,
                tags,
                finalize=finalize,
                is_user_created=is_user_created,
                use_after_commit=use_after_commit,
            )
        return artifact

    def _public_api(self, overrides: Optional[Dict[str, str]] = None) -> PublicApi:
        overrides = {"run": self._run_id}
        if not (self._settings._offline or self._run_obj is None):
            overrides["entity"] = self._run_obj.entity
            overrides["project"] = self._run_obj.project
        return public.Api(overrides)

    # TODO(jhr): annotate this
    def _assert_can_log_artifact(self, artifact) -> None:  # type: ignore
        if self._settings._offline:
            return
        try:
            public_api = self._public_api()
            entity = public_api.settings["entity"]
            project = public_api.settings["project"]
            expected_type = Artifact._expected_type(
                entity, project, artifact.name, public_api.client
            )
        except requests.exceptions.RequestException:
            # Just return early if there is a network error. This is
            # ok, as this function is intended to help catch an invalid
            # type early, but not a hard requirement for valid operation.
            return
        if expected_type is not None and artifact.type != expected_type:
            raise ValueError(
                f"Artifact {artifact.name} already exists with type '{expected_type}'; "
                f"cannot create another with type '{artifact.type}'"
            )
        if entity and artifact._source_entity and entity != artifact._source_entity:
            raise ValueError(
                f"Artifact {artifact.name} is owned by entity "
                f"'{artifact._source_entity}'; it can't be moved to '{entity}'"
            )
        if project and artifact._source_project and project != artifact._source_project:
            raise ValueError(
                f"Artifact {artifact.name} exists in project "
                f"'{artifact._source_project}'; it can't be moved to '{project}'"
            )

    def _prepare_artifact(
        self,
        artifact_or_path: Union[Artifact, StrPath],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
    ) -> Tuple[Artifact, List[str]]:
        if isinstance(artifact_or_path, (str, os.PathLike)):
            name = name or f"run-{self._run_id}-{os.path.basename(artifact_or_path)}"
            artifact = wandb.Artifact(name, type or "unspecified")
            if os.path.isfile(artifact_or_path):
                artifact.add_file(str(artifact_or_path))
            elif os.path.isdir(artifact_or_path):
                artifact.add_dir(str(artifact_or_path))
            elif "://" in str(artifact_or_path):
                artifact.add_reference(str(artifact_or_path))
            else:
                raise ValueError(
                    "path must be a file, directory or external"
                    "reference like s3://bucket/path"
                )
        else:
            artifact = artifact_or_path
        if not isinstance(artifact, wandb.Artifact):
            raise ValueError(
                "You must pass an instance of wandb.Artifact or a "
                "valid file path to log_artifact"
            )

        artifact.finalize()
        return artifact, _resolve_aliases(aliases)

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def log_model(
        self,
        path: StrPath,
        name: Optional[str] = None,
        aliases: Optional[List[str]] = None,
    ) -> None:
        """Logs a model artifact containing the contents inside the 'path' to a run and marks it as an output to this run.

        Arguments:
            path: (str) A path to the contents of this model,
                can be in the following forms:
                    - `/local/directory`
                    - `/local/directory/file.txt`
                    - `s3://bucket/path`
            name: (str, optional) A name to assign to the model artifact that the file contents will be added to.
                The string must contain only the following alphanumeric characters: dashes, underscores, and dots.
                This will default to the basename of the path prepended with the current
                run id  if not specified.
            aliases: (list, optional) Aliases to apply to the created model artifact,
                    defaults to `["latest"]`

        Examples:
            ```python
            run.log_model(
                path="/local/directory",
                name="my_model_artifact",
                aliases=["production"],
            )
            ```

            Invalid usage
            ```python
            run.log_model(
                path="/local/directory",
                name="my_entity/my_project/my_model_artifact",
                aliases=["production"],
            )
            ```

        Raises:
            ValueError: if name has invalid special characters

        Returns:
            None
        """
        self._log_artifact(
            artifact_or_path=path, name=name, type="model", aliases=aliases
        )

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def use_model(self, name: str) -> FilePathStr:
        """Download the files logged in a model artifact 'name'.

        Arguments:
            name: (str) A model artifact name. 'name' must match the name of an existing logged
                model artifact.
                May be prefixed with entity/project/. Valid names
                can be in the following forms:
                    - model_artifact_name:version
                    - model_artifact_name:alias

        Examples:
            ```python
            run.use_model(
                name="my_model_artifact:latest",
            )

            run.use_model(
                name="my_project/my_model_artifact:v0",
            )

            run.use_model(
                name="my_entity/my_project/my_model_artifact:<digest>",
            )
            ```

            Invalid usage
            ```python
            run.use_model(
                name="my_entity/my_project/my_model_artifact",
            )
            ```

        Raises:
            AssertionError: if model artifact 'name' is of a type that does not contain the substring 'model'.

        Returns:
            path: (str) path to downloaded model artifact file(s).
        """
        artifact = self.use_artifact(artifact_or_name=name)
        assert (
            "model" in str(artifact.type.lower())
        ), "You can only use this method for 'model' artifacts. For an artifact to be a 'model' artifact, its type property must contain the substring 'model'."
        path = artifact.download()

        # If returned directory contains only one file, return path to that file
        dir_list = os.listdir(path)
        if len(dir_list) == 1:
            return FilePathStr(os.path.join(path, dir_list[0]))
        return path

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def link_model(
        self,
        path: StrPath,
        registered_model_name: str,
        name: Optional[str] = None,
        aliases: Optional[List[str]] = None,
    ) -> None:
        """Log a model artifact version and link it to a registered model in the model registry.

        The linked model version will be visible in the UI for the specified registered model.

        Steps:
            - Check if 'name' model artifact has been logged. If so, use the artifact version that matches the files
            located at 'path' or log a new version. Otherwise log files under 'path' as a new model artifact, 'name'
            of type 'model'.
            - Check if registered model with name 'registered_model_name' exists in the 'model-registry' project.
            If not, create a new registered model with name 'registered_model_name'.
            - Link version of model artifact 'name' to registered model, 'registered_model_name'.
            - Attach aliases from 'aliases' list to the newly linked model artifact version.

        Arguments:
            path: (str) A path to the contents of this model,
                can be in the following forms:
                    - `/local/directory`
                    - `/local/directory/file.txt`
                    - `s3://bucket/path`
            registered_model_name: (str) - the name of the registered model that the model is to be linked to.
                A registered model is a collection of model versions linked to the model registry, typically representing a
                team's specific ML Task. The entity that this registered model belongs to will be derived from the run
            name: (str, optional) - the name of the model artifact that files in 'path' will be logged to. This will
                default to the basename of the path prepended with the current run id  if not specified.
            aliases: (List[str], optional) - alias(es) that will only be applied on this linked artifact
                inside the registered model.
                The alias "latest" will always be applied to the latest version of an artifact that is linked.

        Examples:
            ```python
            run.link_model(
                path="/local/directory",
                registered_model_name="my_reg_model",
                name="my_model_artifact",
                aliases=["production"],
            )
            ```

            Invalid usage
            ```python
            run.link_model(
                path="/local/directory",
                registered_model_name="my_entity/my_project/my_reg_model",
                name="my_model_artifact",
                aliases=["production"],
            )

            run.link_model(
                path="/local/directory",
                registered_model_name="my_reg_model",
                name="my_entity/my_project/my_model_artifact",
                aliases=["production"],
            )
            ```

        Raises:
            AssertionError: if registered_model_name is a path or
                if model artifact 'name' is of a type that does not contain the substring 'model'
            ValueError: if name has invalid special characters

        Returns:
            None
        """
        name_parts = registered_model_name.split("/")
        assert (
            len(name_parts) == 1
        ), "Please provide only the name of the registered model. Do not append the entity or project name."
        project = "model-registry"
        target_path = self.entity + "/" + project + "/" + registered_model_name

        public_api = self._public_api()
        try:
            artifact = public_api.artifact(name=f"{name}:latest")
            assert (
                "model" in str(artifact.type.lower())
            ), "You can only use this method for 'model' artifacts. For an artifact to be a 'model' artifact, its type property must contain the substring 'model'."
            artifact = self._log_artifact(
                artifact_or_path=path, name=name, type=artifact.type
            )
        except (ValueError, CommError):
            artifact = self._log_artifact(
                artifact_or_path=path, name=name, type="model"
            )
        self.link_artifact(artifact=artifact, target_path=target_path, aliases=aliases)

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def alert(
        self,
        title: str,
        text: str,
        level: Optional[Union[str, "AlertLevel"]] = None,
        wait_duration: Union[int, float, timedelta, None] = None,
    ) -> None:
        """Launch an alert with the given title and text.

        Arguments:
            title: (str) The title of the alert, must be less than 64 characters long.
            text: (str) The text body of the alert.
            level: (str or AlertLevel, optional) The alert level to use, either: `INFO`, `WARN`, or `ERROR`.
            wait_duration: (int, float, or timedelta, optional) The time to wait (in seconds) before sending another
                alert with this title.
        """
        level = level or AlertLevel.INFO
        level_str: str = level.value if isinstance(level, AlertLevel) else level
        if level_str not in {lev.value for lev in AlertLevel}:
            raise ValueError("level must be one of 'INFO', 'WARN', or 'ERROR'")

        wait_duration = wait_duration or timedelta(minutes=1)
        if isinstance(wait_duration, int) or isinstance(wait_duration, float):
            wait_duration = timedelta(seconds=wait_duration)
        elif not callable(getattr(wait_duration, "total_seconds", None)):
            raise ValueError(
                "wait_duration must be an int, float, or datetime.timedelta"
            )
        wait_duration = int(wait_duration.total_seconds() * 1000)

        if self._backend and self._backend.interface:
            self._backend.interface.publish_alert(title, text, level_str, wait_duration)

    def __enter__(self) -> "Run":
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException],
        exc_val: BaseException,
        exc_tb: TracebackType,
    ) -> bool:
        exception_raised = exc_type is not None
        if exception_raised:
            traceback.print_exception(exc_type, exc_val, exc_tb)
        exit_code = 1 if exception_raised else 0
        self._finish(exit_code=exit_code)
        return not exception_raised

    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def mark_preempting(self) -> None:
        """Mark this run as preempting.

        Also tells the internal process to immediately report this to server.
        """
        if self._backend and self._backend.interface:
            self._backend.interface.publish_preempting()

    @property
    @_run_decorator._noop_on_finish()
    @_run_decorator._attach
    def _system_metrics(self) -> Dict[str, List[Tuple[datetime, float]]]:
        """Returns a dictionary of system metrics.

        Returns:
            A dictionary of system metrics.
        """

        def pb_to_dict(
            system_metrics_pb: wandb.proto.wandb_internal_pb2.GetSystemMetricsResponse,
        ) -> Dict[str, List[Tuple[datetime, float]]]:
            res = {}

            for metric, records in system_metrics_pb.system_metrics.items():
                measurements = []
                for record in records.record:
                    # Convert timestamp to datetime
                    dt = datetime.fromtimestamp(
                        record.timestamp.seconds, tz=timezone.utc
                    )
                    dt = dt.replace(microsecond=record.timestamp.nanos // 1000)

                    measurements.append((dt, record.value))

                res[metric] = measurements

            return res

        if not self._backend or not self._backend.interface:
            return {}

        handle = self._backend.interface.deliver_get_system_metrics()
        result = handle.wait(timeout=1)

        if result:
            try:
                response = result.response.get_system_metrics_response
                if response:
                    return pb_to_dict(response)
            except Exception as e:
                logger.error("Error getting system metrics: %s", e)
        return {}

    # ------------------------------------------------------------------------------
    # HEADER
    # ------------------------------------------------------------------------------
    # Note: All the header methods are static methods since we want to share the printing logic
    # with the service execution path that doesn't have access to the run instance
    @staticmethod
    def _header(
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        Run._header_wandb_version_info(settings=settings, printer=printer)
        Run._header_sync_info(settings=settings, printer=printer)
        Run._header_run_info(settings=settings, printer=printer)

    @staticmethod
    def _header_wandb_version_info(
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        if settings.quiet or settings.silent:
            return

        # TODO: add this to a higher verbosity level
        printer.display(
            f"Tracking run with wandb version {wandb.__version__}", off=False
        )

    @staticmethod
    def _header_sync_info(
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        if settings._offline:
            printer.display(
                [
                    f"W&B syncing is set to {printer.code('`offline`')} in this directory.  ",
                    f"Run {printer.code('`wandb online`')} or set {printer.code('WANDB_MODE=online')} "
                    "to enable cloud syncing.",
                ]
            )
        else:
            info = [f"Run data is saved locally in {printer.files(settings.sync_dir)}"]
            if not printer._html:
                info.append(
                    f"Run {printer.code('`wandb offline`')} to turn off syncing."
                )
            printer.display(info, off=settings.quiet or settings.silent)

    @staticmethod
    def _header_run_info(
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        if settings._offline or settings.silent:
            return

        run_url = settings.run_url
        project_url = settings.project_url
        sweep_url = settings.sweep_url

        run_state_str = (
            "Resuming run"
            if settings.resumed or settings.resume_from
            else "Syncing run"
        )
        run_name = settings.run_name
        if not run_name:
            return

        if printer._html:
            if not wandb.jupyter.maybe_display():  # type: ignore
                run_line = f"<strong>{printer.link(run_url, run_name)}</strong>"
                project_line, sweep_line = "", ""

                # TODO(settings): make settings the source of truth
                if not wandb.jupyter.quiet():  # type: ignore
                    doc_html = printer.link(wburls.get("doc_run"), "docs")

                    project_html = printer.link(project_url, "Weights & Biases")
                    project_line = f"to {project_html} ({doc_html})"

                    if sweep_url:
                        sweep_line = f"Sweep page: {printer.link(sweep_url, sweep_url)}"

                printer.display(
                    [f"{run_state_str} {run_line} {project_line}", sweep_line],
                )

        else:
            printer.display(
                f"{run_state_str} {printer.name(run_name)}", off=not run_name
            )

        if not settings.quiet:
            # TODO: add verbosity levels and add this to higher levels
            printer.display(
                f'{printer.emoji("star")} View project at {printer.link(project_url)}'
            )
            if sweep_url:
                printer.display(
                    f'{printer.emoji("broom")} View sweep at {printer.link(sweep_url)}'
                )
        printer.display(
            f'{printer.emoji("rocket")} View run at {printer.link(run_url)}',
        )

        # TODO(settings) use `wandb_settings` (if self.settings.anonymous == "true":)
        if Api().api.settings().get("anonymous") == "true":
            printer.display(
                "Do NOT share these links with anyone. They can be used to claim your runs.",
                level="warn",
                off=not run_name,
            )

    # ------------------------------------------------------------------------------
    # FOOTER
    # ------------------------------------------------------------------------------
    # Note: All the footer methods are static methods since we want to share the printing logic
    # with the service execution path that doesn't have access to the run instance
    @staticmethod
    def _footer(
        sampled_history: Optional["SampledHistoryResponse"] = None,
        final_summary: Optional["GetSummaryResponse"] = None,
        poll_exit_response: Optional[PollExitResponse] = None,
        internal_messages_response: Optional["InternalMessagesResponse"] = None,
        reporter: Optional[Reporter] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        Run._footer_history_summary_info(
            history=sampled_history,
            summary=final_summary,
            quiet=quiet,
            settings=settings,
            printer=printer,
        )

        Run._footer_sync_info(
            poll_exit_response=poll_exit_response,
            quiet=quiet,
            settings=settings,
            printer=printer,
        )
        Run._footer_log_dir_info(quiet=quiet, settings=settings, printer=printer)
        Run._footer_notify_wandb_core(
            quiet=quiet,
            settings=settings,
            printer=printer,
        )
        Run._footer_internal_messages(
            internal_messages_response=internal_messages_response,
            quiet=quiet,
            settings=settings,
            printer=printer,
        )
        Run._footer_reporter_warn_err(
            reporter=reporter, quiet=quiet, settings=settings, printer=printer
        )

    # fixme: Temporary hack until we move to rich which allows multiple spinners
    @staticmethod
    def _footer_file_pusher_status_info(
        poll_exit_responses: Optional[
            Union[PollExitResponse, List[Optional[PollExitResponse]]]
        ] = None,
        *,
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        if not poll_exit_responses:
            return
        if isinstance(poll_exit_responses, PollExitResponse):
            Run._footer_single_run_file_pusher_status_info(
                poll_exit_responses, printer=printer
            )
        elif isinstance(poll_exit_responses, list):
            poll_exit_responses_list = poll_exit_responses
            assert all(
                response is None or isinstance(response, PollExitResponse)
                for response in poll_exit_responses_list
            )
            if len(poll_exit_responses_list) == 0:
                return
            elif len(poll_exit_responses_list) == 1:
                Run._footer_single_run_file_pusher_status_info(
                    poll_exit_responses_list[0], printer=printer
                )
            else:
                Run._footer_multiple_runs_file_pusher_status_info(
                    poll_exit_responses_list, printer=printer
                )
        else:
            logger.error(
                f"Got the type `{type(poll_exit_responses)}` for `poll_exit_responses`. "
                "Expected either None, PollExitResponse or a List[Union[PollExitResponse, None]]"
            )

    @staticmethod
    def _footer_single_run_file_pusher_status_info(
        poll_exit_response: Optional[PollExitResponse] = None,
        *,
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        # todo: is this same as settings._offline?
        if not poll_exit_response:
            return

        stats = poll_exit_response.pusher_stats

        megabyte = wandb.util.POW_2_BYTES[2][1]
        line = (
            f"{stats.uploaded_bytes / megabyte:.3f} MB"
            f" of {stats.total_bytes / megabyte:.3f} MB uploaded"
        )
        if stats.deduped_bytes > 0:
            line += f" ({stats.deduped_bytes / megabyte:.3f} MB deduped)"
        line += "\r"

        if stats.total_bytes > 0:
            printer.progress_update(line, stats.uploaded_bytes / stats.total_bytes)
        else:
            printer.progress_update(line, 1.0)

        if poll_exit_response.done:
            printer.progress_close()

            if stats.total_bytes > 0:
                dedupe_fraction = stats.deduped_bytes / float(stats.total_bytes)
            else:
                dedupe_fraction = 0

            if stats.deduped_bytes > 0.01:
                printer.display(
                    f"W&B sync reduced upload amount by {dedupe_fraction:.1%}"
                )

    @staticmethod
    def _footer_multiple_runs_file_pusher_status_info(
        poll_exit_responses: List[Optional[PollExitResponse]],
        *,
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        # todo: is this same as settings._offline?
        if not all(poll_exit_responses):
            return

        megabyte = wandb.util.POW_2_BYTES[2][1]
        total_files: int = sum(
            sum(
                [
                    response.file_counts.wandb_count,
                    response.file_counts.media_count,
                    response.file_counts.artifact_count,
                    response.file_counts.other_count,
                ]
            )
            for response in poll_exit_responses
            if response is not None and response.file_counts is not None
        )
        uploaded = sum(
            response.pusher_stats.uploaded_bytes
            for response in poll_exit_responses
            if response is not None and response.pusher_stats is not None
        )
        total = sum(
            response.pusher_stats.total_bytes
            for response in poll_exit_responses
            if response is not None and response.pusher_stats is not None
        )

        line = (
            f"Processing {len(poll_exit_responses)} runs with {total_files} files "
            f"({uploaded/megabyte :.2f} MB/{total/megabyte :.2f} MB)\r"
        )
        # line = "{}{:<{max_len}}\r".format(line, " ", max_len=(80 - len(line)))
        printer.progress_update(line)  # type:ignore[call-arg]

        done = all(
            [
                poll_exit_response.done
                for poll_exit_response in poll_exit_responses
                if poll_exit_response
            ]
        )
        if done:
            printer.progress_close()

    @staticmethod
    def _footer_sync_info(
        poll_exit_response: Optional[PollExitResponse] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        if settings.silent:
            return

        if settings._offline:
            printer.display(
                [
                    "You can sync this run to the cloud by running:",
                    printer.code(f"wandb sync {settings.sync_dir}"),
                ],
                off=(quiet or settings.quiet),
            )
        else:
            info = []
            if settings.run_name and settings.run_url:
                info.append(
                    f"{printer.emoji('rocket')} View run {printer.name(settings.run_name)} at: {printer.link(settings.run_url)}"
                )
            if settings.project_url:
                info.append(
                    f"{printer.emoji('star')} View project at: {printer.link(settings.project_url)}"
                )
            if poll_exit_response and poll_exit_response.file_counts:
                logger.info("logging synced files")
                file_counts = poll_exit_response.file_counts
                info.append(
                    f"Synced {file_counts.wandb_count} W&B file(s), {file_counts.media_count} media file(s), "
                    f"{file_counts.artifact_count} artifact file(s) and {file_counts.other_count} other file(s)",
                )
            printer.display(info)

    @staticmethod
    def _footer_log_dir_info(
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        if (quiet or settings.quiet) or settings.silent:
            return

        log_dir = settings.log_user or settings.log_internal
        if log_dir:
            log_dir = os.path.dirname(log_dir.replace(os.getcwd(), "."))
            printer.display(
                f"Find logs at: {printer.files(log_dir)}",
            )

    @staticmethod
    def _footer_history_summary_info(
        history: Optional["SampledHistoryResponse"] = None,
        summary: Optional["GetSummaryResponse"] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        if (quiet or settings.quiet) or settings.silent:
            return

        panel = []

        # Render history if available
        if history:
            logger.info("rendering history")

            sampled_history = {
                item.key: wandb.util.downsample(
                    item.values_float or item.values_int, 40
                )
                for item in history.item
                if not item.key.startswith("_")
            }

            history_rows = []
            for key, values in sorted(sampled_history.items()):
                if any(not isinstance(value, numbers.Number) for value in values):
                    continue
                sparkline = printer.sparklines(values)
                if sparkline:
                    history_rows.append([key, sparkline])
            if history_rows:
                history_grid = printer.grid(
                    history_rows,
                    "Run history:",
                )
                panel.append(history_grid)

        # Render summary if available
        if summary:
            final_summary = {}
            for item in summary.item:
                if item.key.startswith("_") or len(item.nested_key) > 0:
                    continue
                final_summary[item.key] = json.loads(item.value_json)

            logger.info("rendering summary")
            summary_rows = []
            for key, value in sorted(final_summary.items()):
                # arrays etc. might be too large. for now, we just don't print them
                if isinstance(value, str):
                    value = value[:20] + "..." * (len(value) >= 20)
                    summary_rows.append([key, value])
                elif isinstance(value, numbers.Number):
                    value = round(value, 5) if isinstance(value, float) else value
                    summary_rows.append([key, str(value)])
                else:
                    continue

            if summary_rows:
                summary_grid = printer.grid(
                    summary_rows,
                    "Run summary:",
                )
                panel.append(summary_grid)

        if panel:
            printer.display(printer.panel(panel))

    @staticmethod
    def _footer_internal_messages(
        internal_messages_response: Optional["InternalMessagesResponse"] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        if (quiet or settings.quiet) or settings.silent:
            return

        if not internal_messages_response:
            return

        for message in internal_messages_response.messages.warning:
            printer.display(message, level="warn")

    @staticmethod
    def _footer_notify_wandb_core(
        *,
        quiet: Optional[bool] = None,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        """Prints a message advertising the upcoming core release."""
        if quiet or not settings._require_legacy_service:
            return

        printer.display(
            "The legacy backend is deprecated. In future versions, `wandb-core` will become "
            "the sole backend service, and the `wandb.require('legacy-service')` flag will be removed. "
            "For more information, visit https://wandb.me/wandb-core",
            level="warn",
        )

    @staticmethod
    def _footer_reporter_warn_err(
        reporter: Optional[Reporter] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        if (quiet or settings.quiet) or settings.silent:
            return

        if not reporter:
            return

        warning_lines = reporter.warning_lines
        if warning_lines:
            warnings = ["Warnings:"] + [f"{line}" for line in warning_lines]
            if len(warning_lines) < reporter.warning_count:
                warnings.append("More warnings...")
            printer.display(warnings)

        error_lines = reporter.error_lines
        if error_lines:
            errors = ["Errors:"] + [f"{line}" for line in error_lines]
            if len(error_lines) < reporter.error_count:
                errors.append("More errors...")
            printer.display(errors)


# We define this outside of the run context to support restoring before init
def restore(
    name: str,
    run_path: Optional[str] = None,
    replace: bool = False,
    root: Optional[str] = None,
) -> Union[None, TextIO]:
    """Download the specified file from cloud storage.

    File is placed into the current directory or run directory.
    By default, will only download the file if it doesn't already exist.

    Arguments:
        name: the name of the file
        run_path: optional path to a run to pull files from, i.e. `username/project_name/run_id`
            if wandb.init has not been called, this is required.
        replace: whether to download the file even if it already exists locally
        root: the directory to download the file to.  Defaults to the current
            directory or the run directory if wandb.init was called.

    Returns:
        None if it can't find the file, otherwise a file object open for reading

    Raises:
        wandb.CommError: if we can't connect to the wandb backend
        ValueError: if the file is not found or can't find run_path
    """
    is_disabled = wandb.run is not None and wandb.run.disabled
    run = None if is_disabled else wandb.run
    if run_path is None:
        if run is not None:
            run_path = run.path
        else:
            raise ValueError(
                "run_path required when calling wandb.restore before wandb.init"
            )
    if root is None:
        if run is not None:
            root = run.dir
    api = public.Api()
    api_run = api.run(run_path)
    if root is None:
        root = os.getcwd()
    path = os.path.join(root, name)
    if os.path.exists(path) and replace is False:
        return open(path)
    if is_disabled:
        return None
    files = api_run.files([name])
    if len(files) == 0:
        return None
    # if the file does not exist, the file has an md5 of 0
    if files[0].md5 == "0":
        raise ValueError(f"File {name} not found in {run_path or root}.")
    return files[0].download(root=root, replace=True)


# propagate our doc string to the runs restore method
try:
    Run.restore.__doc__ = restore.__doc__
except AttributeError:
    pass


def finish(exit_code: Optional[int] = None, quiet: Optional[bool] = None) -> None:
    """Mark a run as finished, and finish uploading all data.

    This is used when creating multiple runs in the same process.
    We automatically call this method when your script exits.

    Arguments:
        exit_code: Set to something other than 0 to mark a run as failed
        quiet: Set to true to minimize log output
    """
    if wandb.run:
        wandb.run.finish(exit_code=exit_code, quiet=quiet)
