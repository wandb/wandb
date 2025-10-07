from __future__ import annotations

import asyncio
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
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from types import TracebackType
from typing import TYPE_CHECKING, Callable, Sequence, TextIO, TypeVar

import requests
from typing_extensions import Any, Concatenate, Literal, NamedTuple, ParamSpec

import wandb
import wandb.env
import wandb.util
from wandb import trigger
from wandb.apis import internal, public
from wandb.apis.public import Api as PublicApi
from wandb.errors import CommError, UsageError
from wandb.errors.links import url_registry
from wandb.integration.torch import wandb_torch
from wandb.plot import CustomChart, Visualize
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto.wandb_deprecated import Deprecated
from wandb.proto.wandb_internal_pb2 import (
    MetricRecord,
    PollExitResponse,
    Result,
    RunRecord,
)
from wandb.sdk.artifacts._internal_artifact import InternalArtifact
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.internal import job_builder
from wandb.sdk.lib import asyncio_compat, wb_logging
from wandb.sdk.lib.import_hooks import (
    register_post_import_hook,
    unregister_post_import_hook,
)
from wandb.sdk.lib.paths import FilePathStr, StrPath
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
from .artifacts._validators import (
    MAX_ARTIFACT_METADATA_KEYS,
    ArtifactPath,
    validate_aliases,
    validate_tags,
)
from .data_types._dtypes import TypeRegistry
from .interface.interface import FilesDict, GlobStr, InterfaceBase, PolicyName
from .interface.summary_record import SummaryRecord
from .lib import (
    config_util,
    deprecate,
    filenames,
    filesystem,
    interrupt,
    ipython,
    module,
    printer,
    progress,
    proto_util,
    redirect,
    telemetry,
)
from .lib.exit_hooks import ExitHooks
from .mailbox import (
    HandleAbandonedError,
    MailboxClosedError,
    MailboxHandle,
    wait_with_progress,
)
from .wandb_alerts import AlertLevel
from .wandb_settings import Settings
from .wandb_setup import _WandbSetup

if TYPE_CHECKING:
    from typing import TypedDict

    import torch  # type: ignore [import-not-found]

    import wandb.apis.public
    import wandb.sdk.backend.backend
    import wandb.sdk.interface.interface_queue
    from wandb.proto.wandb_internal_pb2 import (
        GetSummaryResponse,
        InternalMessagesResponse,
        SampledHistoryResponse,
    )

    class GitSourceDict(TypedDict):
        remote: str
        commit: str
        entrypoint: list[str]
        args: Sequence[str]

    class ArtifactSourceDict(TypedDict):
        artifact: str
        entrypoint: list[str]
        args: Sequence[str]

    class ImageSourceDict(TypedDict):
        image: str
        args: Sequence[str]

    class JobSourceDict(TypedDict, total=False):
        _version: str
        source_type: str
        source: GitSourceDict | ArtifactSourceDict | ImageSourceDict
        input_types: dict[str, Any]
        output_types: dict[str, Any]
        runtime: str | None
        services: dict[str, str]


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
    _stop_status_handle: MailboxHandle[Result] | None
    _network_status_lock: threading.Lock
    _network_status_handle: MailboxHandle[Result] | None
    _internal_messages_lock: threading.Lock
    _internal_messages_handle: MailboxHandle[Result] | None

    def __init__(
        self,
        run_id: str,
        interface: InterfaceBase,
        settings: Settings,
        stop_polling_interval: int = 15,
        retry_polling_interval: int = 5,
        internal_messages_polling_interval: int = 10,
    ) -> None:
        self._run_id = run_id
        self._interface = interface
        self._stop_polling_interval = stop_polling_interval
        self._retry_polling_interval = retry_polling_interval
        self._internal_messages_polling_interval = internal_messages_polling_interval
        self._settings = settings

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
        handle: MailboxHandle[Result] | None,
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
        local_handle: MailboxHandle[Result] | None = None
        join_requested = False
        while not join_requested:
            time_probe = time.monotonic()
            if not local_handle:
                try:
                    local_handle = request()
                except MailboxClosedError:
                    # This can happen if the service process dies.
                    break
            assert local_handle

            with lock:
                if self._join_event.is_set():
                    break
                set_handle(local_handle)

            try:
                result = local_handle.wait_or(timeout=timeout)
            except HandleAbandonedError:
                # This can happen if the service process dies.
                break
            except TimeoutError:
                result = None

            with lock:
                set_handle(None)

            if result:
                process(result)
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
                        f"{hr.http_status_code} encountered ({hr.http_response_text.rstrip()}), retrying request"
                    )

        with wb_logging.log_to_run(self._run_id):
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
                    interrupt.interrupt_main()
                    return

        with wb_logging.log_to_run(self._run_id):
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
            if (
                not self._settings.show_warnings
                or self._settings.quiet
                or self._settings.silent
            ):
                return
            internal_messages = result.response.internal_messages_response
            for msg in internal_messages.messages.warning:
                wandb.termwarn(msg, repeat=False)

        with wb_logging.log_to_run(self._run_id):
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


_P = ParamSpec("_P")
_T = TypeVar("_T")


def _log_to_run(
    func: Callable[Concatenate[Run, _P], _T],
) -> Callable[Concatenate[Run, _P], _T]:
    """Decorate a Run method to set the run ID in the logging context.

    Any logs during the execution of the method go to the run's log file
    and not to other runs' log files.

    This is meant for use on all public methods and some callbacks. Private
    methods can be assumed to be called from some public method somewhere.
    The general rule is to use it on methods that can be called from a
    context that isn't specific to this run (such as all user code or
    internal methods that aren't run-specific).
    """

    @functools.wraps(func)
    def wrapper(self: Run, *args, **kwargs) -> _T:
        # In "attach" usage, many properties of the Run are not initially
        # populated.
        if hasattr(self, "_settings"):
            run_id = self._settings.run_id
        else:
            run_id = self._attach_id

        with wb_logging.log_to_run(run_id):
            return func(self, *args, **kwargs)

    return wrapper


_is_attaching: str = ""


def _attach(
    func: Callable[Concatenate[Run, _P], _T],
) -> Callable[Concatenate[Run, _P], _T]:
    """Decorate a Run method to auto-attach when in a new process.

    When in a forked process or using a pickled Run instance, this automatically
    connects to the service process to "attach" to the existing run.
    """

    @functools.wraps(func)
    def wrapper(self: Run, *args, **kwargs) -> _T:
        global _is_attaching

        # The _attach_id attribute is only None when running in the "disable
        # service" mode.
        #
        # Since it is set early in `__init__` and included in the run's pickled
        # state, the attribute always exists.
        is_using_service = self._attach_id is not None

        # The _attach_pid attribute is not pickled, so it might not exist.
        # It is set when the run is initialized.
        attach_pid = getattr(self, "_attach_pid", None)

        if is_using_service and attach_pid != os.getpid():
            if _is_attaching:
                raise RuntimeError(
                    f"Trying to attach `{func.__name__}`"
                    f" while in the middle of attaching `{_is_attaching}`"
                )

            _is_attaching = func.__name__
            try:
                wandb._attach(run=self)  # type: ignore
            finally:
                _is_attaching = ""

        return func(self, *args, **kwargs)

    return wrapper


def _raise_if_finished(
    func: Callable[Concatenate[Run, _P], _T],
) -> Callable[Concatenate[Run, _P], _T]:
    """Decorate a Run method to raise an error after the run is finished."""

    @functools.wraps(func)
    def wrapper_fn(self: Run, *args, **kwargs) -> _T:
        if not getattr(self, "_is_finished", False):
            return func(self, *args, **kwargs)

        message = (
            f"Run ({self.id}) is finished. The call to"
            f" `{func.__name__}` will be ignored."
            f" Please make sure that you are using an active run."
        )

        raise UsageError(message)

    return wrapper_fn


@dataclass
class RunStatus:
    sync_items_total: int = field(default=0)
    sync_items_pending: int = field(default=0)
    sync_time: datetime | None = field(default=None)


class Run:
    """A unit of computation logged by W&B. Typically, this is an ML experiment.

    Call [`wandb.init()`](https://docs.wandb.ai/ref/python/init/) to create a
    new run. `wandb.init()` starts a new run and returns a `wandb.Run` object.
    Each run is associated with a unique ID (run ID). W&B recommends using
    a context (`with` statement) manager to automatically finish the run.

    For distributed training experiments, you can either track each process
    separately using one run per process or track all processes to a single run.
    See [Log distributed training experiments](https://docs.wandb.ai/guides/track/log/distributed-training)
    for more information.

    You can log data to a run with `wandb.Run.log()`. Anything you log using
    `wandb.Run.log()` is sent to that run. See
    [Create an experiment](https://docs.wandb.ai/guides/track/launch) or
    [`wandb.init`](https://docs.wandb.ai/ref/python/init/) API reference page
    or more information.

    There is a another `Run` object in the
    [`wandb.apis.public`](https://docs.wandb.ai/ref/python/public-api/api/)
    namespace. Use this object is to interact with runs that have already been
    created.

    Attributes:
        summary: (Summary) A summary of the run, which is a dictionary-like
            object. For more information, see
            [Log summary metrics](https://docs.wandb.ai/guides/track/log/log-summary/).

    Examples:
    Create a run with `wandb.init()`:

    ```python
    import wandb

    # Start a new run and log some data
    # Use context manager (`with` statement) to automatically finish the run
    with wandb.init(entity="entity", project="project") as run:
        run.log({"accuracy": acc, "loss": loss})
    ```

    <!-- lazydoc-ignore-init: internal -->
    """

    _telemetry_obj: telemetry.TelemetryRecord
    _telemetry_obj_active: bool
    _telemetry_obj_dirty: bool
    _telemetry_obj_flushed: bytes

    _teardown_hooks: list[TeardownHook]

    _backend: wandb.sdk.backend.backend.Backend | None
    _internal_run_interface: wandb.sdk.interface.interface_queue.InterfaceQueue | None
    _wl: _WandbSetup | None

    _out_redir: redirect.RedirectBase | None
    _err_redir: redirect.RedirectBase | None
    _redirect_cb: Callable[[str, str], None] | None
    _redirect_raw_cb: Callable[[str, str], None] | None
    _output_writer: filesystem.CRDedupedFile | None

    _atexit_cleanup_called: bool
    _hooks: ExitHooks | None
    _exit_code: int | None

    _run_status_checker: RunStatusChecker | None

    _sampled_history: SampledHistoryResponse | None
    _final_summary: GetSummaryResponse | None
    _poll_exit_handle: MailboxHandle[Result] | None
    _poll_exit_response: PollExitResponse | None
    _internal_messages_response: InternalMessagesResponse | None

    _stdout_slave_fd: int | None
    _stderr_slave_fd: int | None
    _artifact_slots: list[str]

    _init_pid: int
    _attach_pid: int

    _attach_id: str | None
    _is_attached: bool
    _is_finished: bool
    _settings: Settings

    _forked: bool

    _launch_artifacts: dict[str, Any] | None
    _printer: printer.Printer

    summary: wandb_summary.Summary

    def __init__(
        self,
        settings: Settings,
        config: dict[str, Any] | None = None,
        sweep_config: dict[str, Any] | None = None,
        launch_config: dict[str, Any] | None = None,
    ) -> None:
        # pid is set, so we know if this run object was initialized by this process
        self._init_pid = os.getpid()
        self._attach_id = None

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
        config: dict[str, Any] | None = None,
        sweep_config: dict[str, Any] | None = None,
        launch_config: dict[str, Any] | None = None,
    ) -> None:
        self._settings = settings

        self._config = wandb_config.Config()
        self._config._set_callback(self._config_callback)
        self._config._set_artifact_callback(self._config_artifact_callback)
        self._config._set_settings(self._settings)

        # The _wandb key is always expected on the run config.
        wandb_key = "_wandb"
        self._config._update({wandb_key: dict()})

        # TODO: perhaps this should be a property that is a noop on a finished run
        self.summary = wandb_summary.Summary(
            self._summary_get_current_summary_callback,
        )
        self.summary._set_update_callback(self._summary_update_callback)

        self._step = 0
        self._starting_step = 0
        self._start_runtime = 0
        # TODO: eventually would be nice to make this configurable using self._settings._start_time
        #  need to test (jhr): if you set start time to 2 days ago and run a test for 15 minutes,
        #  does the total time get calculated right (not as 2 days and 15 minutes)?
        self._start_time = time.time()

        self._printer = printer.new_printer(settings)

        self._torch_history: wandb_torch.TorchHistory | None = None  # type: ignore

        self._backend = None
        self._internal_run_interface = None
        self._wl = None

        self._hooks = None
        self._teardown_hooks = []

        self._output_writer = None
        self._out_redir = None
        self._err_redir = None
        self._stdout_slave_fd = None
        self._stderr_slave_fd = None

        self._exit_code = None
        self._exit_result = None

        self._used_artifact_slots: dict[str, str] = {}

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

        # Initial scope setup for sentry.
        # This might get updated when the actual run comes back.
        wandb._sentry.configure_scope(
            tags=dict(self._settings),
            process_context="user",
        )

        self._launch_artifact_mapping: dict[str, Any] = {}
        self._unique_launch_artifact_sequence_names: dict[str, Any] = {}

        # Populate config
        config = config or dict()
        self._config._update(config, allow_val_change=True, ignore_locked=True)

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

        self._attach_id = None
        self._is_attached = False
        self._is_finished = False

        self._attach_pid = os.getpid()
        self._forked = False
        # for now, use runid as attach id, this could/should be versioned in the future
        self._attach_id = self._settings.run_id

    def _handle_launch_artifact_overrides(self) -> None:
        if self._settings.launch and (os.environ.get("WANDB_ARTIFACTS") is not None):
            try:
                artifacts: dict[str, Any] = json.loads(
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

    def _initialize_launch_artifact_maps(self, artifacts: dict[str, Any]) -> None:
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
        if not hasattr(self, "_telemetry_obj") or self._is_finished:
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

    def __deepcopy__(self, memo: dict[int, Any]) -> Run:
        return self

    def __getstate__(self) -> Any:
        """Return run state as a custom pickle."""
        # We only pickle in service mode
        if not self._settings:
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
    def _torch(self) -> wandb_torch.TorchHistory:  # type: ignore
        if self._torch_history is None:
            self._torch_history = wandb_torch.TorchHistory()  # type: ignore
        return self._torch_history

    @property
    @_log_to_run
    @_attach
    def settings(self) -> Settings:
        """A frozen copy of run's Settings object."""
        return self._settings.model_copy(deep=True)

    @property
    @_log_to_run
    @_attach
    def dir(self) -> str:
        """The directory where files associated with the run are saved."""
        return self._settings.files_dir

    @property
    @_log_to_run
    @_attach
    def config(self) -> wandb_config.Config:
        """Config object associated with this run."""
        return self._config

    @property
    @_log_to_run
    @_attach
    def config_static(self) -> wandb_config.ConfigStatic:
        """Static config object associated with this run."""
        return wandb_config.ConfigStatic(self._config)

    @property
    @_log_to_run
    @_attach
    def name(self) -> str | None:
        """Display name of the run.

        Display names are not guaranteed to be unique and may be descriptive.
        By default, they are randomly generated.
        """
        return self._settings.run_name

    @name.setter
    @_log_to_run
    @_raise_if_finished
    def name(self, name: str) -> None:
        with telemetry.context(run=self) as tel:
            tel.feature.set_run_name = True
        self._settings.run_name = name
        if self._backend and self._backend.interface:
            self._backend.interface.publish_run(self)

    @property
    @_log_to_run
    @_attach
    def notes(self) -> str | None:
        """Notes associated with the run, if there are any.

        Notes can be a multiline string and can also use markdown and latex
        equations inside `$$`, like `$x + 3$`.
        """
        return self._settings.run_notes

    @notes.setter
    @_log_to_run
    @_raise_if_finished
    def notes(self, notes: str) -> None:
        self._settings.run_notes = notes
        if self._backend and self._backend.interface:
            self._backend.interface.publish_run(self)

    @property
    @_log_to_run
    @_attach
    def tags(self) -> tuple | None:
        """Tags associated with the run, if there are any."""
        return self._settings.run_tags or ()

    @tags.setter
    @_log_to_run
    @_raise_if_finished
    def tags(self, tags: Sequence) -> None:
        with telemetry.context(run=self) as tel:
            tel.feature.set_run_tags = True

        try:
            self._settings.run_tags = tuple(tags)
        except ValueError as e:
            # For runtime tag setting, warn instead of crash
            # Extract the core error message without the pydantic wrapper
            error_msg = str(e)
            if "Value error," in error_msg:
                # Extract the actual error message after "Value error, "
                error_msg = error_msg.split("Value error, ")[1].split(" [type=")[0]
            wandb.termwarn(f"Invalid tag detected: {error_msg} Tags not updated.")
            return

        if self._backend and self._backend.interface:
            self._backend.interface.publish_run(self)

    @property
    @_log_to_run
    @_attach
    def id(self) -> str:
        """Identifier for this run."""
        assert self._settings.run_id is not None
        return self._settings.run_id

    @property
    @_log_to_run
    @_attach
    def sweep_id(self) -> str | None:
        """Identifier for the sweep associated with the run, if there is one."""
        return self._settings.sweep_id

    def _get_path(self) -> str:
        return "/".join(
            e
            for e in [
                self._settings.entity,
                self._settings.project,
                self._settings.run_id,
            ]
            if e is not None
        )

    @property
    @_log_to_run
    @_attach
    def path(self) -> str:
        """Path to the run.

        Run paths include entity, project, and run ID, in the format
        `entity/project/run_id`.
        """
        return self._get_path()

    @property
    @_log_to_run
    @_attach
    def start_time(self) -> float:
        """Unix timestamp (in seconds) of when the run started."""
        return self._start_time

    @property
    @_log_to_run
    @_attach
    def starting_step(self) -> int:
        """The first step of the run.

        <!-- lazydoc-ignore: internal -->
        """
        return self._starting_step

    @property
    @_log_to_run
    @_attach
    def resumed(self) -> bool:
        """True if the run was resumed, False otherwise."""
        return self._settings.resumed

    @property
    @_log_to_run
    @_attach
    def step(self) -> int:
        """Current value of the step.

        This counter is incremented by `wandb.Run.log()`.

        <!-- lazydoc-ignore: internal -->
        """
        return self._step

    @property
    @_log_to_run
    @_attach
    def offline(self) -> bool:
        """True if the run is offline, False otherwise."""
        return self._settings._offline

    @property
    @_log_to_run
    @_attach
    def disabled(self) -> bool:
        """True if the run is disabled, False otherwise."""
        return self._settings._noop

    @property
    @_log_to_run
    @_attach
    def group(self) -> str:
        """Returns the name of the group associated with this run.

        Grouping runs together allows related experiments to be organized and
        visualized collectively in the W&B UI. This is especially useful for
        scenarios such as distributed training or cross-validation, where
        multiple runs should be viewed and managed as a unified experiment.

        In shared mode, where all processes share the same run object,
        setting a group is usually unnecessary, since there is only one
        run and no grouping is required.
        """
        return self._settings.run_group or ""

    @property
    @_log_to_run
    @_attach
    def job_type(self) -> str:
        """Name of the job type associated with the run.

        View a run's job type in the run's Overview page in the W&B App.

        You can use this to categorize runs by their job type, such as
        "training", "evaluation", or "inference". This is useful for organizing
        and filtering runs in the W&B UI, especially when you have multiple
        runs with different job types in the same project. For more
        information, see [Organize runs](https://docs.wandb.ai/guides/runs/#organize-runs).
        """
        return self._settings.run_job_type or ""

    def project_name(self) -> str:
        """This method is deprecated and will be removed in a future release. Use `run.project` instead.

        Name of the W&B project associated with the run.

        <!-- lazydoc-ignore: internal -->
        """
        deprecate.deprecate(
            field_name=Deprecated.run__project_name,
            warning_message=(
                "The project_name method is deprecated and will be removed in a"
                " future release. Please use `run.project` instead."
            ),
        )
        return self.project

    @property
    @_log_to_run
    @_attach
    def project(self) -> str:
        """Name of the W&B project associated with the run."""
        assert self._settings.project is not None
        return self._settings.project

    @_log_to_run
    def get_project_url(self) -> str | None:
        """This method is deprecated and will be removed in a future release. Use `run.project_url` instead.

        URL of the W&B project associated with the run, if there is one.
        Offline runs do not have a project URL.

        <!-- lazydoc-ignore: internal -->
        """
        deprecate.deprecate(
            field_name=Deprecated.run__get_project_url,
            warning_message=(
                "The get_project_url method is deprecated and will be removed in a"
                " future release. Please use `run.project_url` instead."
            ),
        )
        return self.project_url

    @property
    @_log_to_run
    @_attach
    def project_url(self) -> str | None:
        """URL of the W&B project associated with the run, if there is one.

        Offline runs do not have a project URL.
        """
        if self._settings._offline:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._settings.project_url

    @_raise_if_finished
    @_log_to_run
    @_attach
    def log_code(
        self,
        root: str | None = ".",
        name: str | None = None,
        include_fn: Callable[[str, str], bool]
        | Callable[[str], bool] = _is_py_requirements_or_dockerfile,
        exclude_fn: Callable[[str, str], bool]
        | Callable[[str], bool] = filenames.exclude_wandb_fn,
    ) -> Artifact | None:
        """Save the current state of your code to a W&B Artifact.

        By default, it walks the current directory and logs all files that end with `.py`.

        Args:
            root: The relative (to `os.getcwd()`) or absolute path to recursively find code from.
            name: (str, optional) The name of our code artifact. By default, we'll name
                the artifact `source-$PROJECT_ID-$ENTRYPOINT_RELPATH`. There may be scenarios where you want
                many runs to share the same artifact. Specifying name allows you to achieve that.
            include_fn: A callable that accepts a file path and (optionally) root path and
                returns True when it should be included and False otherwise. This
                defaults to `lambda path, root: path.endswith(".py")`.
            exclude_fn: A callable that accepts a file path and (optionally) root path and
                returns `True` when it should be excluded and `False` otherwise. This
                defaults to a function that excludes all files within `<root>/.wandb/`
                and `<root>/wandb/` directories.

        Examples:
        Basic usage

        ```python
        import wandb

        with wandb.init() as run:
            run.log_code()
        ```

        Advanced usage

        ```python
        import wandb

        with wandb.init() as run:
            run.log_code(
                root="../",
                include_fn=lambda path: path.endswith(".py") or path.endswith(".ipynb"),
                exclude_fn=lambda path, root: os.path.relpath(path, root).startswith(
                    "cache/"
                ),
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
                elif self.settings.x_jupyter_path:
                    if self.settings.x_jupyter_path.startswith("fileId="):
                        notebook_name = self.settings.x_jupyter_name
                    else:
                        notebook_name = self.settings.x_jupyter_path
                name_string = f"{self._settings.project}-{notebook_name}"
            else:
                name_string = (
                    f"{self._settings.project}-{self._settings.program_relpath}"
                )
            name = wandb.util.make_artifact_name_safe(f"source-{name_string}")
        art = InternalArtifact(name, "code")
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

        artifact = self._log_artifact(art)

        self._config.update(
            {"_wandb": {"code_path": artifact.name}},
            allow_val_change=True,
        )

        return artifact

    @_log_to_run
    def get_sweep_url(self) -> str | None:
        """This method is deprecated and will be removed in a future release. Use `run.sweep_url` instead.

        The URL of the sweep associated with the run, if there is one.
        Offline runs do not have a sweep URL.

        <!-- lazydoc-ignore: internal -->
        """
        deprecate.deprecate(
            field_name=Deprecated.run__get_sweep_url,
            warning_message=(
                "The get_sweep_url method is deprecated and will be removed in a"
                " future release. Please use `run.sweep_url` instead."
            ),
        )
        return self.sweep_url

    @property
    @_attach
    def sweep_url(self) -> str | None:
        """URL of the sweep associated with the run, if there is one.

        Offline runs do not have a sweep URL.
        """
        if self._settings._offline:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._settings.sweep_url

    @_log_to_run
    def get_url(self) -> str | None:
        """This method is deprecated and will be removed in a future release. Use `run.url` instead.

        URL of the W&B run, if there is one. Offline runs do not have a URL.

        <!-- lazydoc-ignore: internal -->
        """
        deprecate.deprecate(
            field_name=Deprecated.run__get_url,
            warning_message=(
                "The get_url method is deprecated and will be removed in a"
                " future release. Please use `run.url` instead."
            ),
        )
        return self.url

    @property
    @_log_to_run
    @_attach
    def url(self) -> str | None:
        """The url for the W&B run, if there is one.

        Offline runs will not have a url.
        """
        if self._settings._offline:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._settings.run_url

    @property
    @_log_to_run
    @_attach
    def entity(self) -> str:
        """The name of the W&B entity associated with the run.

        Entity can be a username or the name of a team or organization.
        """
        return self._settings.entity or ""

    def _label_internal(
        self,
        code: str | None = None,
        repo: str | None = None,
        code_version: str | None = None,
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
        code: str | None = None,
        repo: str | None = None,
        code_version: str | None = None,
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

    def _label_probe_lines(self, lines: list[str]) -> None:
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

    @_log_to_run
    @_attach
    def display(self, height: int = 420, hidden: bool = False) -> bool:
        """Display this run in Jupyter."""
        if self._settings.silent:
            return False

        if not ipython.in_jupyter():
            return False

        try:
            from IPython import display
        except ImportError:
            wandb.termwarn(".display() only works in jupyter environments")
            return False

        display.display(display.HTML(self.to_html(height, hidden)))
        return True

    @_log_to_run
    @_attach
    def to_html(self, height: int = 420, hidden: bool = False) -> str:
        """Generate HTML containing an iframe displaying the current run.

        <!-- lazydoc-ignore: internal -->
        """
        url = self._settings.run_url + "?jupyter=true"
        style = f"border:none;width:100%;height:{height}px;"
        prefix = ""
        if hidden:
            style += "display:none;"
            prefix = ipython.toggle_button()
        return prefix + f"<iframe src={url!r} style={style!r}></iframe>"

    def _repr_mimebundle_(
        self, include: Any | None = None, exclude: Any | None = None
    ) -> dict[str, str]:
        return {"text/html": self.to_html(hidden=True)}

    @_log_to_run
    @_raise_if_finished
    def _config_callback(
        self,
        key: tuple[str, ...] | str | None = None,
        val: Any | None = None,
        data: dict[str, object] | None = None,
    ) -> None:
        logger.info(f"config_cb {key} {val} {data}")
        if self._backend and self._backend.interface:
            self._backend.interface.publish_config(key=key, val=val, data=data)

    @_log_to_run
    def _config_artifact_callback(
        self, key: str, val: str | Artifact | dict
    ) -> Artifact:
        # artifacts can look like dicts as they are passed into the run config
        # since the run config stores them on the backend as a dict with fields shown
        # in wandb.util.artifact_to_json
        if _is_artifact_version_weave_dict(val):
            assert isinstance(val, dict)
            public_api = self._public_api()
            artifact = Artifact._from_id(val["id"], public_api.client)

            assert artifact
            return self.use_artifact(artifact)
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
                artifact = public_api._artifact(name=artifact_string)
            # in the future we'll need to support using artifacts from
            # different instances of wandb.

            assert artifact
            return self.use_artifact(artifact)
        elif _is_artifact_object(val):
            return self.use_artifact(val)
        else:
            raise ValueError(
                f"Cannot call _config_artifact_callback on type {type(val)}"
            )

    def _set_config_wandb(self, key: str, val: Any) -> None:
        self._config_callback(key=("_wandb", key), val=val)

    @_log_to_run
    @_raise_if_finished
    def _summary_update_callback(self, summary_record: SummaryRecord) -> None:
        with telemetry.context(run=self) as tel:
            tel.feature.set_summary = True
        if self._backend and self._backend.interface:
            self._backend.interface.publish_summary(self, summary_record)

    @_log_to_run
    def _summary_get_current_summary_callback(self) -> dict[str, Any]:
        if self._is_finished:
            # TODO: WB-18420: fetch summary from backend and stage it before run is finished
            wandb.termwarn("Summary data not available in finished run")
            return {}
        if not self._backend or not self._backend.interface:
            return {}
        handle = self._backend.interface.deliver_get_summary()

        try:
            result = handle.wait_or(timeout=self._settings.summary_timeout)
        except TimeoutError:
            return {}

        get_summary_response = result.response.get_summary_response
        return proto_util.dict_from_proto_list(get_summary_response.item)

    @_log_to_run
    def _metric_callback(self, metric_record: MetricRecord) -> None:
        if self._backend and self._backend.interface:
            self._backend.interface._publish_metric(metric_record)

    @_log_to_run
    def _publish_file(self, fname: str) -> None:
        """Mark a run file to be uploaded with the run.

        This is a W&B-internal function: it can be used by other internal
        wandb code.

        Args:
            fname: The path to the file in the run's files directory, relative
                to the run's files directory.
        """
        if not self._backend or not self._backend.interface:
            return
        files: FilesDict = dict(files=[(GlobStr(fname), "now")])
        self._backend.interface.publish_files(files)

    def _pop_all_charts(
        self,
        data: dict[str, Any],
        key_prefix: str | None = None,
    ) -> dict[str, Any]:
        """Pops all charts from a dictionary including nested charts.

        This function will return a mapping of the charts and a dot-separated
        key for each chart. Indicating the path to the chart in the data dictionary.
        """
        keys_to_remove = set()
        charts: dict[str, Any] = {}
        for k, v in data.items():
            key = f"{key_prefix}.{k}" if key_prefix else k
            if isinstance(v, Visualize):
                keys_to_remove.add(k)
                charts[key] = v
            elif isinstance(v, CustomChart):
                keys_to_remove.add(k)
                charts[key] = v
            elif isinstance(v, dict):
                nested_charts = self._pop_all_charts(v, key)
                charts.update(nested_charts)

        for k in keys_to_remove:
            data.pop(k)

        return charts

    def _serialize_custom_charts(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Process and replace chart objects with their underlying table values.

        This processes the chart objects passed to `wandb.Run.log()`, replacing their entries
        in the given dictionary (which is saved to the run's history) and adding them
        to the run's config.

        Args:
            data: Dictionary containing data that may include plot objects
                Plot objects can be nested in dictionaries, which will be processed recursively.

        Returns:
            The processed dictionary with custom charts transformed into tables.
        """
        if not data:
            return data

        charts = self._pop_all_charts(data)
        for k, v in charts.items():
            v.set_key(k)
            self._config_callback(
                val=v.spec.config_value,
                key=v.spec.config_key,
            )

            if isinstance(v, CustomChart):
                data[v.spec.table_key] = v.table
            elif isinstance(v, Visualize):
                data[k] = v.table

        return data

    @_log_to_run
    def _partial_history_callback(
        self,
        data: dict[str, Any],
        step: int | None = None,
        commit: bool | None = None,
    ) -> None:
        if not (self._backend and self._backend.interface):
            return

        data = data.copy()  # avoid modifying the original data

        # Serialize custom charts before publishing
        data = self._serialize_custom_charts(data)

        not_using_tensorboard = len(wandb.patched["tensorboard"]) == 0
        self._backend.interface.publish_partial_history(
            self,
            data,
            user_step=self._step,
            step=step,
            flush=commit,
            publish_step=not_using_tensorboard,
        )

    @_log_to_run
    def _console_callback(self, name: str, data: str) -> None:
        # logger.info("console callback: %s, %s", name, data)
        if self._backend and self._backend.interface:
            self._backend.interface.publish_output(name, data)

    @_log_to_run
    @_raise_if_finished
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

    @_log_to_run
    def _tensorboard_callback(
        self, logdir: str, save: bool = True, root_logdir: str = ""
    ) -> None:
        logger.info("tensorboard callback: %s, %s", logdir, save)
        if self._backend and self._backend.interface:
            self._backend.interface.publish_tbdata(logdir, save, root_logdir)

    def _set_library(self, library: _WandbSetup) -> None:
        self._wl = library

    def _set_backend(self, backend: wandb.sdk.backend.backend.Backend) -> None:
        self._backend = backend

    def _set_internal_run_interface(
        self,
        interface: wandb.sdk.interface.interface_queue.InterfaceQueue,
    ) -> None:
        self._internal_run_interface = interface

    def _set_teardown_hooks(self, hooks: list[TeardownHook]) -> None:
        self._teardown_hooks = hooks

    def _set_run_obj(self, run_obj: RunRecord) -> None:  # noqa: C901
        if run_obj.starting_step:
            self._starting_step = run_obj.starting_step
            self._step = run_obj.starting_step

        if run_obj.start_time:
            self._start_time = run_obj.start_time.ToMicroseconds() / 1e6

        if run_obj.runtime:
            self._start_runtime = run_obj.runtime

        # Grab the config from resuming
        if run_obj.config:
            c_dict = config_util.dict_no_value_from_proto_list(run_obj.config.update)
            # We update the config object here without triggering the callback
            self._config._update(c_dict, allow_val_change=True, ignore_locked=True)
        # Update the summary, this will trigger an un-needed graphql request :(
        if run_obj.summary:
            summary_dict = {}
            for orig in run_obj.summary.update:
                summary_dict[orig.key] = json.loads(orig.value_json)
            if summary_dict:
                self.summary.update(summary_dict)

        # update settings from run_obj
        if run_obj.run_id:
            self._settings.run_id = run_obj.run_id
        if run_obj.entity:
            self._settings.entity = run_obj.entity
        if run_obj.project:
            self._settings.project = run_obj.project
        if run_obj.run_group:
            self._settings.run_group = run_obj.run_group
        if run_obj.job_type:
            self._settings.run_job_type = run_obj.job_type
        if run_obj.display_name:
            self._settings.run_name = run_obj.display_name
        if run_obj.notes:
            self._settings.run_notes = run_obj.notes
        if run_obj.tags:
            self._settings.run_tags = tuple(run_obj.tags)
        if run_obj.sweep_id:
            self._settings.sweep_id = run_obj.sweep_id
        if run_obj.host:
            self._settings.host = run_obj.host
        if run_obj.resumed:
            self._settings.resumed = run_obj.resumed
        if run_obj.git:
            if run_obj.git.remote_url:
                self._settings.git_remote_url = run_obj.git.remote_url
            if run_obj.git.commit:
                self._settings.git_commit = run_obj.git.commit

        if run_obj.forked:
            self._forked = run_obj.forked

        wandb._sentry.configure_scope(
            process_context="user",
            tags=dict(self._settings),
        )

    def _populate_git_info(self) -> None:
        from .lib.gitlib import GitRepo

        # Use user-provided git info if available, otherwise resolve it from the environment
        try:
            repo = GitRepo(
                root=self._settings.git_root,
                remote=self._settings.git_remote,
                remote_url=self._settings.git_remote_url,
                commit=self._settings.git_commit,
                lazy=False,
            )
            self._settings.git_remote_url = repo.remote_url
            self._settings.git_commit = repo.last_commit
        except Exception:
            wandb.termwarn("Cannot find valid git repo associated with this directory.")

    def _add_singleton(
        self, data_type: str, key: str, value: dict[int | str, str]
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
        data: dict[str, Any],
        step: int | None = None,
        commit: bool | None = None,
    ) -> None:
        if not isinstance(data, Mapping):
            raise TypeError("wandb.log must be passed a dictionary")

        if any(not isinstance(key, str) for key in data.keys()):
            raise TypeError("Key values passed to `wandb.log` must be strings.")

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

    @_log_to_run
    @_raise_if_finished
    @_attach
    def log(
        self,
        data: dict[str, Any],
        step: int | None = None,
        commit: bool | None = None,
    ) -> None:
        """Upload run data.

        Use `log` to log data from runs, such as scalars, images, video,
        histograms, plots, and tables. See [Log objects and media](https://docs.wandb.ai/guides/track/log) for
        code snippets, best practices, and more.

        Basic usage:

        ```python
        import wandb

        with wandb.init() as run:
            run.log({"train-loss": 0.5, "accuracy": 0.9})
        ```

        The previous code snippet saves the loss and accuracy to the run's
        history and updates the summary values for these metrics.

        Visualize logged data in a workspace at [wandb.ai](https://wandb.ai),
        or locally on a [self-hosted instance](https://docs.wandb.ai/guides/hosting)
        of the W&B app, or export data to visualize and explore locally, such as in a
        Jupyter notebook, with the [Public API](https://docs.wandb.ai/guides/track/public-api-guide).

        Logged values don't have to be scalars. You can log any
        [W&B supported Data Type](https://docs.wandb.ai/ref/python/data-types/)
        such as images, audio, video, and more. For example, you can use
        `wandb.Table` to log structured data. See
        [Log tables, visualize and query data](https://docs.wandb.ai/guides/models/tables/tables-walkthrough)
        tutorial for more details.

        W&B organizes metrics with a forward slash (`/`) in their name
        into sections named using the text before the final slash. For example,
        the following results in two sections named "train" and "validate":

        ```python
        with wandb.init() as run:
            # Log metrics in the "train" section.
            run.log(
                {
                    "train/accuracy": 0.9,
                    "train/loss": 30,
                    "validate/accuracy": 0.8,
                    "validate/loss": 20,
                }
            )
        ```

        Only one level of nesting is supported; `run.log({"a/b/c": 1})`
        produces a section named "a/b".

        `run.log()` is not intended to be called more than a few times per second.
        For optimal performance, limit your logging to once every N iterations,
        or collect data over multiple iterations and log it in a single step.

        By default, each call to `log` creates a new "step".
        The step must always increase, and it is not possible to log
        to a previous step. You can use any metric as the X axis in charts.
        See [Custom log axes](https://docs.wandb.ai/guides/track/log/customize-logging-axes/)
        for more details.

        In many cases, it is better to treat the W&B step like
        you'd treat a timestamp rather than a training step.

        ```python
        with wandb.init() as run:
            # Example: log an "epoch" metric for use as an X axis.
            run.log({"epoch": 40, "train-loss": 0.5})
        ```

        It is possible to use multiple `wandb.Run.log()` invocations to log to
        the same step with the `step` and `commit` parameters.
        The following are all equivalent:

        ```python
        with wandb.init() as run:
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

        Args:
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

        Examples:
        For more and more detailed examples, see
        [our guides to logging](https://docs.wandb.com/guides/track/log).

        Basic usage

        ```python
        import wandb

        with wandb.init() as run:
            run.log({"train-loss": 0.5, "accuracy": 0.9
        ```

        Incremental logging

        ```python
        import wandb

        with wandb.init() as run:
            run.log({"loss": 0.2}, commit=False)
            # Somewhere else when I'm ready to report this step:
            run.log({"accuracy": 0.8})
        ```

        Histogram

        ```python
        import numpy as np
        import wandb

        # sample gradients at random from normal distribution
        gradients = np.random.randn(100, 100)
        with wandb.init() as run:
            run.log({"gradients": wandb.Histogram(gradients)})
        ```

        Image from NumPy

        ```python
        import numpy as np
        import wandb

        with wandb.init() as run:
            examples = []
            for i in range(3):
                pixels = np.random.randint(low=0, high=256, size=(100, 100, 3))
                image = wandb.Image(pixels, caption=f"random field {i}")
                examples.append(image)
            run.log({"examples": examples})
        ```

        Image from PIL

        ```python
        import numpy as np
        from PIL import Image as PILImage
        import wandb

        with wandb.init() as run:
            examples = []
            for i in range(3):
                pixels = np.random.randint(
                    low=0,
                    high=256,
                    size=(100, 100, 3),
                    dtype=np.uint8,
                )
                pil_image = PILImage.fromarray(pixels, mode="RGB")
                image = wandb.Image(pil_image, caption=f"random field {i}")
                examples.append(image)
            run.log({"examples": examples})
        ```

        Video from NumPy

        ```python
        import numpy as np
        import wandb

        with wandb.init() as run:
            # axes are (time, channel, height, width)
            frames = np.random.randint(
                low=0,
                high=256,
                size=(10, 3, 100, 100),
                dtype=np.uint8,
            )
            run.log({"video": wandb.Video(frames, fps=4)})
        ```

        Matplotlib plot

        ```python
        from matplotlib import pyplot as plt
        import numpy as np
        import wandb

        with wandb.init() as run:
            fig, ax = plt.subplots()
            x = np.linspace(0, 10)
            y = x * x
            ax.plot(x, y)  # plot y = x^2
            run.log({"chart": fig})
        ```

        PR Curve

        ```python
        import wandb

        with wandb.init() as run:
            run.log({"pr": wandb.plot.pr_curve(y_test, y_probas, labels)})
        ```

        3D Object

        ```python
        import wandb

        with wandb.init() as run:
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
            wandb.Error: If called before `wandb.init()`.
            ValueError: If invalid data is passed.

        """
        if step is not None:
            with telemetry.context(run=self) as tel:
                tel.feature.set_step_log = True

        if self._settings._shared and step is not None:
            wandb.termwarn(
                "In shared mode, the use of `wandb.log` with the step argument is not supported "
                f"and will be ignored. Please refer to {url_registry.url('define-metric')} "
                "on how to customize your x-axis.",
                repeat=False,
            )
        self._log(data=data, step=step, commit=commit)

    @_log_to_run
    @_raise_if_finished
    @_attach
    def save(
        self,
        glob_str: str | os.PathLike,
        base_path: str | os.PathLike | None = None,
        policy: PolicyName = "live",
    ) -> bool | list[str]:
        """Sync one or more files to W&B.

        Relative paths are relative to the current working directory.

        A Unix glob, such as "myfiles/*", is expanded at the time `save` is
        called regardless of the `policy`. In particular, new files are not
        picked up automatically.

        A `base_path` may be provided to control the directory structure of
        uploaded files. It should be a prefix of `glob_str`, and the directory
        structure beneath it is preserved.

        When given an absolute path or glob and no `base_path`, one
        directory level is preserved as in the example above.

        Files are automatically deduplicated: calling `save()` multiple times
        on the same file without modifications will not re-upload it.

        Args:
            glob_str: A relative or absolute path or Unix glob.
            base_path: A path to use to infer a directory structure; see examples.
            policy: One of `live`, `now`, or `end`.
            - live: upload the file as it changes, overwriting the previous version
            - now: upload the file once now
            - end: upload file when the run ends

        Returns:
            Paths to the symlinks created for the matched files.

            For historical reasons, this may return a boolean in legacy code.

        ```python
        import wandb

        run = wandb.init()

        run.save("these/are/myfiles/*")
        # => Saves files in a "these/are/myfiles/" folder in the run.

        run.save("these/are/myfiles/*", base_path="these")
        # => Saves files in an "are/myfiles/" folder in the run.

        run.save("/Users/username/Documents/run123/*.txt")
        # => Saves files in a "run123/" folder in the run. See note below.

        run.save("/Users/username/Documents/run123/*.txt", base_path="/Users")
        # => Saves files in a "username/Documents/run123/" folder in the run.

        run.save("files/*/saveme.txt")
        # => Saves each "saveme.txt" file in an appropriate subdirectory
        #    of "files/".

        # Explicitly finish the run since a context manager is not used.
        run.finish()
        ```
        """
        if isinstance(glob_str, bytes):
            # Preserved for backward compatibility: allow bytes inputs.
            glob_str = glob_str.decode("utf-8")
        if isinstance(glob_str, str) and (glob_str.startswith(("gs://", "s3://"))):
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
        policy: PolicyName,
    ) -> list[str]:
        # Can't use is_relative_to() because that's added in Python 3.9,
        # but we support down to Python 3.8.
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
            target_path.unlink(missing_ok=True)

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

    @_log_to_run
    @_attach
    def restore(
        self,
        name: str,
        run_path: str | None = None,
        replace: bool = False,
        root: str | None = None,
    ) -> None | TextIO:
        return restore(
            name,
            run_path or self._get_path(),
            replace,
            root or self._settings.files_dir,
        )

    @_log_to_run
    @_attach
    def finish(
        self,
        exit_code: int | None = None,
        quiet: bool | None = None,
    ) -> None:
        """Finish a run and upload any remaining data.

        Marks the completion of a W&B run and ensures all data is synced to the server.
        The run's final state is determined by its exit conditions and sync status.

        Run States:
        - Running: Active run that is logging data and/or sending heartbeats.
        - Crashed: Run that stopped sending heartbeats unexpectedly.
        - Finished: Run completed successfully (`exit_code=0`) with all data synced.
        - Failed: Run completed with errors (`exit_code!=0`).
        - Killed: Run was forcibly stopped before it could finish.

        Args:
            exit_code: Integer indicating the run's exit status. Use 0 for success,
                any other value marks the run as failed.
            quiet: Deprecated. Configure logging verbosity using `wandb.Settings(quiet=...)`.
        """
        if quiet is not None:
            deprecate.deprecate(
                field_name=Deprecated.run__finish_quiet,
                warning_message=(
                    "The `quiet` argument to `wandb.run.finish()` is deprecated, "
                    "use `wandb.Settings(quiet=...)` to set this instead."
                ),
                run=self,
            )
        return self._finish(exit_code)

    @_log_to_run
    def _finish(
        self,
        exit_code: int | None = None,
    ) -> None:
        if self._is_finished:
            return

        assert self._wl

        logger.info(f"finishing run {self._get_path()}")
        with telemetry.context(run=self) as tel:
            tel.feature.finish = True

        # Run hooks that need to happen before the last messages to the
        # internal service, like Jupyter hooks.
        for hook in self._teardown_hooks:
            if hook.stage == TeardownStage.EARLY:
                hook.call()

        # Early-stage hooks may use methods that require _is_finished
        # to be False, so we set this after running those hooks.
        self._is_finished = True
        self._wl.remove_active_run(self)

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
            if self._settings.run_id:
                service = self._wl.assert_service()
                service.inform_finish(run_id=self._settings.run_id)

        finally:
            if wandb.run is self:
                module.unset_globals()
            wandb._sentry.end_session()

    @_log_to_run
    @_raise_if_finished
    @_attach
    def status(
        self,
    ) -> RunStatus:
        """Get sync info from the internal backend, about the current run's sync status."""
        if not self._backend or not self._backend.interface:
            return RunStatus()

        handle_run_status = self._backend.interface.deliver_request_run_status()
        result = handle_run_status.wait_or(timeout=None)
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

    def _add_panel(
        self, visualize_key: str, panel_type: str, panel_config: dict
    ) -> None:
        config = {
            "panel_type": panel_type,
            "panel_config": panel_config,
        }
        self._config_callback(val=config, key=("_wandb", "visualize", visualize_key))

    def _redirect(
        self,
        stdout_slave_fd: int | None,
        stderr_slave_fd: int | None,
        console: str | None = None,
    ) -> None:
        if console is None:
            console = self._settings.console
        # only use raw for service to minimize potential changes
        if console == "wrap":
            console = "wrap_raw"
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
                flush_periodically=(self._settings.mode == "online"),
            )
            err_redir = redirect.Redirect(
                src="stderr",
                cbs=[
                    lambda data: self._console_callback("stderr", data),
                    self._output_writer.write,  # type: ignore
                ],
                flush_periodically=(self._settings.mode == "online"),
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
                flush_periodically=(self._settings.mode == "online"),
            )
            err_redir = redirect.StreamWrapper(
                src="stderr",
                cbs=[
                    lambda data: self._console_callback("stderr", data),
                    self._output_writer.write,  # type: ignore
                ],
                flush_periodically=(self._settings.mode == "online"),
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
            out_redir.install()
            err_redir.install()
            self._out_redir = out_redir
            self._err_redir = err_redir
            logger.info("Redirects installed.")
        except Exception as e:
            wandb.termwarn(f"Failed to redirect: {e}")
            logger.exception("Failed to redirect.")
        return

    def _restore(self) -> None:
        logger.info("restore")
        # TODO(jhr): drain and shutdown all threads
        if self._out_redir:
            self._out_redir.uninstall()
        if self._err_redir:
            self._err_redir.uninstall()
        logger.info("restore done")

    def _atexit_cleanup(self, exit_code: int | None = None) -> None:
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

        except Exception:
            self._console_stop()
            logger.exception("Problem finishing run")
            wandb.termerror("Problem finishing run")
            raise

        Run._footer(
            sampled_history=self._sampled_history,
            final_summary=self._final_summary,
            poll_exit_response=self._poll_exit_response,
            internal_messages_response=self._internal_messages_response,
            settings=self._settings,
            printer=self._printer,
        )

    def _console_start(self) -> None:
        logger.info("atexit reg")
        self._hooks = ExitHooks()

        self._redirect(self._stdout_slave_fd, self._stderr_slave_fd)

    def _console_stop(self) -> None:
        self._restore()
        if self._output_writer:
            self._output_writer.close()
            self._output_writer = None

    def _on_start(self) -> None:
        self._header()

        if self._settings.save_code and self._settings.code_dir is not None:
            self.log_code(self._settings.code_dir)

        if self._settings.x_save_requirements:
            if self._backend and self._backend.interface:
                from wandb.util import working_set

                logger.debug(
                    "Saving list of pip packages installed into the current environment"
                )
                self._backend.interface.publish_python_packages(working_set())

        if self._backend and self._backend.interface and not self._settings._offline:
            assert self._settings.run_id
            self._run_status_checker = RunStatusChecker(
                self._settings.run_id,
                interface=self._backend.interface,
                settings=self._settings,
            )
            self._run_status_checker.start()

        self._console_start()
        self._on_ready()

    def _on_attach(self) -> None:
        """Event triggered when run is attached to another run."""
        with telemetry.context(run=self) as tel:
            tel.feature.attach = True

        self._is_attached = True
        self._on_ready()

    def _register_telemetry_import_hooks(
        self,
    ) -> None:
        def _telemetry_import_hook(
            run: Run,
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
        if not self._settings.run_id:
            return
        for module_name in import_telemetry_set:
            register_post_import_hook(
                import_hook_fn,
                self._settings.run_id,
                module_name,
            )

    def _on_ready(self) -> None:
        """Event triggered when run is ready for the user."""
        assert self._wl
        self._wl.add_active_run(self)

        self._register_telemetry_import_hooks()

        # start reporting any telemetry changes
        self._telemetry_obj_active = True
        self._telemetry_flush()

        try:
            self._detect_and_apply_job_inputs()
        except Exception:
            logger.exception("Problem applying launch job inputs")

        # object is about to be returned to the user, don't let them modify it
        self._freeze()

        if not self._settings.resume:
            if os.path.exists(self._settings.resume_fname):
                os.remove(self._settings.resume_fname)

    def _detect_and_apply_job_inputs(self) -> None:
        """If the user has staged launch inputs, apply them to the run."""
        from wandb.sdk.launch.inputs.internal import StagedLaunchInputs

        StagedLaunchInputs().apply(self)

    def _make_job_source_reqs(self) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
        from wandb.util import working_set

        installed_packages_list = sorted(f"{d.key}=={d.version}" for d in working_set())
        input_types = TypeRegistry.type_of(self.config.as_dict()).to_json()
        output_types = TypeRegistry.type_of(self.summary._as_dict()).to_json()

        return installed_packages_list, input_types, output_types

    def _construct_job_artifact(
        self,
        name: str,
        source_dict: JobSourceDict,
        installed_packages_list: list[str],
        patch_path: os.PathLike | None = None,
    ) -> Artifact:
        job_artifact = InternalArtifact(name, job_builder.JOB_ARTIFACT_TYPE)
        if patch_path and os.path.exists(patch_path):
            job_artifact.add_file(FilePathStr(patch_path), "diff.patch")
        with job_artifact.new_file("requirements.frozen.txt") as f:
            f.write("\n".join(installed_packages_list))
        with job_artifact.new_file("wandb-job.json") as f:
            f.write(json.dumps(source_dict))

        return job_artifact

    def _create_image_job(
        self,
        input_types: dict[str, Any],
        output_types: dict[str, Any],
        installed_packages_list: list[str],
        docker_image_name: str | None = None,
        args: list[str] | None = None,
    ) -> Artifact | None:
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
        self, docker_image_name: str, args: list[str] | None = None
    ) -> Artifact:
        packages, in_types, out_types = self._make_job_source_reqs()
        job_artifact = self._create_image_job(
            in_types,
            out_types,
            packages,
            args=args,
            docker_image_name=docker_image_name,
        )

        assert job_artifact
        artifact = self.log_artifact(job_artifact)

        if not artifact:
            raise wandb.Error(f"Job Artifact log unsuccessful: {artifact}")
        else:
            return artifact

    async def _display_finish_stats(
        self,
        progress_printer: progress.ProgressPrinter,
    ) -> None:
        last_result: Result | None = None

        async def loop_update_printer() -> None:
            while True:
                if last_result:
                    progress_printer.update(
                        [last_result.response.poll_exit_response],
                    )
                await asyncio.sleep(0.1)

        async def loop_poll_exit() -> None:
            nonlocal last_result
            assert self._backend and self._backend.interface

            while True:
                handle = await self._backend.interface.deliver_async(
                    pb.Record(request=pb.Request(poll_exit=pb.PollExitRequest()))
                )

                time_start = time.monotonic()
                last_result = await handle.wait_async(timeout=None)

                # Update at most once a second.
                time_elapsed = time.monotonic() - time_start
                if time_elapsed < 1:
                    await asyncio.sleep(1 - time_elapsed)

        async with asyncio_compat.open_task_group() as task_group:
            task_group.start_soon(loop_update_printer())
            task_group.start_soon(loop_poll_exit())

    def _on_finish(self) -> None:
        trigger.call("on_finished")

        if self._run_status_checker is not None:
            self._run_status_checker.stop()

        self._console_stop()  # TODO: there's a race here with jupyter console logging

        assert self._backend and self._backend.interface

        if self._settings.x_update_finish_state:
            exit_handle = self._backend.interface.deliver_exit(self._exit_code)
        else:
            exit_handle = self._backend.interface.deliver_finish_without_exit()

        with progress.progress_printer(
            self._printer,
            default_text="Finishing up...",
        ) as progress_printer:
            # Wait for the run to complete.
            wait_with_progress(
                exit_handle,
                timeout=None,
                display_progress=functools.partial(
                    self._display_finish_stats,
                    progress_printer,
                ),
            )

        poll_exit_handle = self._backend.interface.deliver_poll_exit()
        result = poll_exit_handle.wait_or(timeout=None)
        self._poll_exit_response = result.response.poll_exit_response

        internal_messages_handle = self._backend.interface.deliver_internal_messages()
        result = internal_messages_handle.wait_or(timeout=None)
        self._internal_messages_response = result.response.internal_messages_response

        # dispatch all our final requests

        final_summary_handle = self._backend.interface.deliver_get_summary()
        sampled_history_handle = (
            self._backend.interface.deliver_request_sampled_history()
        )

        result = sampled_history_handle.wait_or(timeout=None)
        self._sampled_history = result.response.sampled_history_response

        result = final_summary_handle.wait_or(timeout=None)
        self._final_summary = result.response.get_summary_response

        if self._backend:
            self._backend.cleanup()

        if self._run_status_checker:
            self._run_status_checker.join()

        if self._settings.run_id:
            self._unregister_telemetry_import_hooks(self._settings.run_id)

    @staticmethod
    def _unregister_telemetry_import_hooks(run_id: str) -> None:
        import_telemetry_set = telemetry.list_telemetry_imports()
        for module_name in import_telemetry_set:
            unregister_post_import_hook(module_name, run_id)

    @_log_to_run
    @_raise_if_finished
    @_attach
    def define_metric(
        self,
        name: str,
        step_metric: str | wandb_metric.Metric | None = None,
        step_sync: bool | None = None,
        hidden: bool | None = None,
        summary: str | None = None,
        goal: str | None = None,
        overwrite: bool | None = None,
    ) -> wandb_metric.Metric:
        """Customize metrics logged with `wandb.Run.log()`.

        Args:
            name: The name of the metric to customize.
            step_metric: The name of another metric to serve as the X-axis
                for this metric in automatically generated charts.
            step_sync: Automatically insert the last value of step_metric into
                `wandb.Run.log()` if it is not provided explicitly. Defaults to True
                 if step_metric is specified.
            hidden: Hide this metric from automatic plots.
            summary: Specify aggregate metrics added to summary.
                Supported aggregations include "min", "max", "mean", "last",
                "first", "best", "copy" and "none". "none" prevents a summary
                from being generated. "best" is used together with the goal
                parameter, "best" is deprecated and should not be used, use
                "min" or "max" instead. "copy" is deprecated and should not be
                used.
            goal: Specify how to interpret the "best" summary type.
                Supported options are "minimize" and "maximize". "goal" is
                deprecated and should not be used, use "min" or "max" instead.
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
                Deprecated.run__define_metric_copy,
                "define_metric(summary='copy') is deprecated and will be removed.",
                self,
            )

        if (summary and "best" in summary) or goal is not None:
            deprecate.deprecate(
                Deprecated.run__define_metric_best_goal,
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
        step_metric: str | wandb_metric.Metric | None = None,
        step_sync: bool | None = None,
        hidden: bool | None = None,
        summary: str | None = None,
        goal: str | None = None,
        overwrite: bool | None = None,
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
        summary_ops: Sequence[str] | None = None
        if summary:
            summary_items = [s.lower() for s in summary.split(",")]
            summary_ops = []
            valid = {"min", "max", "mean", "best", "last", "copy", "none", "first"}
            # TODO: deprecate copy and best
            for i in summary_items:
                if i not in valid:
                    raise wandb.Error(f"Unhandled define_metric() arg: summary op: {i}")
                summary_ops.append(i)
            with telemetry.context(run=self) as tel:
                tel.feature.metric_summary = True
        # TODO: deprecate goal
        goal_cleaned: str | None = None
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

    @_log_to_run
    @_attach
    def watch(
        self,
        models: torch.nn.Module | Sequence[torch.nn.Module],
        criterion: torch.F | None = None,  # type: ignore
        log: Literal["gradients", "parameters", "all"] | None = "gradients",
        log_freq: int = 1000,
        idx: int | None = None,
        log_graph: bool = False,
    ) -> None:
        """Hook into given PyTorch model to monitor gradients and the model's computational graph.

        This function can track parameters, gradients, or both during training.

        Args:
            models: A single model or a sequence of models to be monitored.
            criterion: The loss function being optimized (optional).
            log: Specifies whether to log "gradients", "parameters", or "all".
                Set to None to disable logging. (default="gradients").
            log_freq: Frequency (in batches) to log gradients and parameters. (default=1000)
            idx: Index used when tracking multiple models with `wandb.watch`. (default=None)
            log_graph: Whether to log the model's computational graph. (default=False)

        Raises:
            ValueError:
                If `wandb.init()` has not been called or if any of the models are not instances
                of `torch.nn.Module`.
        """
        wandb.sdk._watch(self, models, criterion, log, log_freq, idx, log_graph)

    @_log_to_run
    @_attach
    def unwatch(
        self, models: torch.nn.Module | Sequence[torch.nn.Module] | None = None
    ) -> None:
        """Remove pytorch model topology, gradient and parameter hooks.

        Args:
            models: Optional list of pytorch models that have had watch called on them.
        """
        wandb.sdk._unwatch(self, models=models)

    @_log_to_run
    @_raise_if_finished
    @_attach
    def link_artifact(
        self,
        artifact: Artifact,
        target_path: str,
        aliases: list[str] | None = None,
    ) -> Artifact:
        """Link the given artifact to a portfolio (a promoted collection of artifacts).

        Linked artifacts are visible in the UI for the specified portfolio.

        Args:
            artifact: the (public or local) artifact which will be linked
            target_path: `str` - takes the following forms: `{portfolio}`, `{project}/{portfolio}`,
                or `{entity}/{project}/{portfolio}`
            aliases: `List[str]` - optional alias(es) that will only be applied on this linked artifact
                                   inside the portfolio.
            The alias "latest" will always be applied to the latest version of an artifact that is linked.

        Returns:
            The linked artifact.

        """
        if artifact.is_draft() and not artifact._is_draft_save_started():
            artifact = self._log_artifact(artifact)

        if self._settings._offline:
            # TODO: implement offline mode + sync
            raise NotImplementedError

        # Normalize the target "entity/project/collection" with defaults
        # inferred from this run's entity and project, if needed.
        #
        # HOWEVER, if the target path is a registry collection, avoid setting
        # the target entity to the run's entity.  Instead, delegate to
        # Artifact.link() to resolve the required org entity.
        target = ArtifactPath.from_str(target_path)
        if not target.is_registry_path():
            target = target.with_defaults(prefix=self.entity, project=self.project)

        return artifact.link(target.to_str(), aliases)

    @_log_to_run
    @_raise_if_finished
    @_attach
    def use_artifact(
        self,
        artifact_or_name: str | Artifact,
        type: str | None = None,
        aliases: list[str] | None = None,
        use_as: str | None = None,
    ) -> Artifact:
        """Declare an artifact as an input to a run.

        Call `download` or `file` on the returned object to get the contents locally.

        Args:
            artifact_or_name: The name of the artifact to use. May be prefixed
                with the name of the project the artifact was logged to
                ("<entity>" or "<entity>/<project>"). If no
                entity is specified in the name, the Run or API setting's entity is used.
                Valid names can be in the following forms
            - name:version
            - name:alias
            type: The type of artifact to use.
            aliases: Aliases to apply to this artifact
            use_as: This argument is deprecated and does nothing.

        Returns:
            An `Artifact` object.

        Examples:
        ```python
        import wandb

        run = wandb.init(project="<example>")

        # Use an artifact by name and alias
        artifact_a = run.use_artifact(artifact_or_name="<name>:<alias>")

        # Use an artifact by name and version
        artifact_b = run.use_artifact(artifact_or_name="<name>:v<version>")

        # Use an artifact by entity/project/name:alias
        artifact_c = run.use_artifact(
            artifact_or_name="<entity>/<project>/<name>:<alias>"
        )

        # Use an artifact by entity/project/name:version
        artifact_d = run.use_artifact(
            artifact_or_name="<entity>/<project>/<name>:v<version>"
        )

        # Explicitly finish the run since a context manager is not used.
        run.finish()
        ```

        """
        if self._settings._offline:
            raise TypeError("Cannot use artifact when in offline mode.")

        api = internal.Api(
            default_settings={
                "entity": self._settings.entity,
                "project": self._settings.project,
            }
        )
        api.set_current_run_id(self._settings.run_id)

        if use_as is not None:
            deprecate.deprecate(
                field_name=Deprecated.run__use_artifact_use_as,
                warning_message=(
                    "`use_as` argument is deprecated and does not affect the behaviour of `run.use_artifact`"
                ),
            )

        if isinstance(artifact_or_name, str):
            name = artifact_or_name
            public_api = self._public_api()
            artifact = public_api._artifact(type=type, name=name)
            if type is not None and type != artifact.type:
                raise ValueError(
                    f"Supplied type {type} does not match type {artifact.type} of artifact {artifact.name}"
                )
            api.use_artifact(
                artifact.id,
                entity_name=self._settings.entity,
                project_name=self._settings.project,
                artifact_entity_name=artifact.entity,
                artifact_project_name=artifact.project,
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
            elif isinstance(artifact, Artifact) and not artifact.is_draft():
                api.use_artifact(
                    artifact.id,
                    artifact_entity_name=artifact.entity,
                    artifact_project_name=artifact.project,
                )
            else:
                raise ValueError(
                    'You must pass an artifact name (e.g. "pedestrian-dataset:v1"), '
                    "an instance of `wandb.Artifact`, or `wandb.Api().artifact()` to `use_artifact`"
                )
        if self._backend and self._backend.interface:
            self._backend.interface.publish_use_artifact(artifact)
        return artifact

    @_log_to_run
    @_raise_if_finished
    @_attach
    def log_artifact(
        self,
        artifact_or_path: Artifact | StrPath,
        name: str | None = None,
        type: str | None = None,
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> Artifact:
        """Declare an artifact as an output of a run.

        Args:
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

    @_log_to_run
    @_raise_if_finished
    @_attach
    def upsert_artifact(
        self,
        artifact_or_path: Artifact | str,
        name: str | None = None,
        type: str | None = None,
        aliases: list[str] | None = None,
        distributed_id: str | None = None,
    ) -> Artifact:
        """Declare (or append to) a non-finalized artifact as output of a run.

        Note that you must call run.finish_artifact() to finalize the artifact.
        This is useful when distributed jobs need to all contribute to the same artifact.

        Args:
            artifact_or_path: A path to the contents of this artifact,
                can be in the following forms:
            - `/local/directory`
            - `/local/directory/file.txt`
            - `s3://bucket/path`
            name: An artifact name. May be prefixed with "entity/project". Defaults
                to the basename of the path prepended with the current run ID
                if not specified. Valid names can be in the following forms:
            - name:version
            - name:alias
            - digest
            type: The type of artifact to log. Common examples include `dataset`, `model`.
            aliases: Aliases to apply to this artifact, defaults to `["latest"]`.
            distributed_id: Unique string that all distributed jobs share. If None,
                defaults to the run's group name.

        Returns:
            An `Artifact` object.
        """
        if self._settings.run_group is None and distributed_id is None:
            raise TypeError(
                "Cannot upsert artifact unless run is in a group or distributed_id is provided"
            )
        if distributed_id is None:
            distributed_id = self._settings.run_group or ""
        return self._log_artifact(
            artifact_or_path,
            name=name,
            type=type,
            aliases=aliases,
            distributed_id=distributed_id,
            finalize=False,
        )

    @_log_to_run
    @_raise_if_finished
    @_attach
    def finish_artifact(
        self,
        artifact_or_path: Artifact | str,
        name: str | None = None,
        type: str | None = None,
        aliases: list[str] | None = None,
        distributed_id: str | None = None,
    ) -> Artifact:
        """Finishes a non-finalized artifact as output of a run.

        Subsequent "upserts" with the same distributed ID will result in a new version.

        Args:
            artifact_or_path: A path to the contents of this artifact,
                can be in the following forms:
                    - `/local/directory`
                    - `/local/directory/file.txt`
                    - `s3://bucket/path`
                You can also pass an Artifact object created by calling
                `wandb.Artifact`.
            name: An artifact name. May be prefixed with entity/project.
                Valid names can be in the following forms:
                    - name:version
                    - name:alias
                    - digest
                This will default to the basename of the path prepended with the current
                run id  if not specified.
            type: The type of artifact to log, examples include `dataset`, `model`
            aliases: Aliases to apply to this artifact,
                defaults to `["latest"]`
            distributed_id: Unique string that all distributed jobs share. If None,
                defaults to the run's group name.

        Returns:
            An `Artifact` object.
        """
        if self._settings.run_group is None and distributed_id is None:
            raise TypeError(
                "Cannot finish artifact unless run is in a group or distributed_id is provided"
            )
        if distributed_id is None:
            distributed_id = self._settings.run_group or ""

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
        artifact_or_path: Artifact | StrPath,
        name: str | None = None,
        type: str | None = None,
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
        distributed_id: str | None = None,
        finalize: bool = True,
        is_user_created: bool = False,
        use_after_commit: bool = False,
    ) -> Artifact:
        if self._settings.anonymous in ["allow", "must"]:
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

        if len(artifact.metadata) > MAX_ARTIFACT_METADATA_KEYS:
            raise ValueError(
                f"Artifact must not have more than {MAX_ARTIFACT_METADATA_KEYS} metadata keys."
            )

        artifact.distributed_id = distributed_id
        self._assert_can_log_artifact(artifact)
        if self._backend and self._backend.interface:
            if not self._settings._offline:
                handle = self._backend.interface.deliver_artifact(
                    self,
                    artifact,
                    aliases,
                    tags,
                    self.step,
                    finalize=finalize,
                    is_user_created=is_user_created,
                    use_after_commit=use_after_commit,
                )
                artifact._set_save_handle(handle, self._public_api().client)
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

    def _public_api(self, overrides: dict[str, str] | None = None) -> PublicApi:
        overrides = {"run": self._settings.run_id}  # type: ignore
        if not self._settings._offline:
            overrides["entity"] = self._settings.entity or ""
            overrides["project"] = self._settings.project or ""
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
        artifact_or_path: Artifact | StrPath,
        name: str | None = None,
        type: str | None = None,
        aliases: list[str] | None = None,
    ) -> tuple[Artifact, list[str]]:
        if isinstance(artifact_or_path, (str, os.PathLike)):
            name = (
                name
                or f"run-{self._settings.run_id}-{os.path.basename(artifact_or_path)}"
            )
            artifact = Artifact(name, type or "unspecified")
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
        if not isinstance(artifact, Artifact):
            raise TypeError(
                "You must pass an instance of wandb.Artifact or a "
                "valid file path to log_artifact"
            )

        artifact.finalize()
        return artifact, _resolve_aliases(aliases)

    @_log_to_run
    @_raise_if_finished
    @_attach
    def log_model(
        self,
        path: StrPath,
        name: str | None = None,
        aliases: list[str] | None = None,
    ) -> None:
        """Logs a model artifact containing the contents inside the 'path' to a run and marks it as an output to this run.

        The name of model artifact can only contain alphanumeric characters,
        underscores, and hyphens.

        Args:
            path: (str) A path to the contents of this model,
                can be in the following forms:
                    - `/local/directory`
                    - `/local/directory/file.txt`
                    - `s3://bucket/path`
            name: A name to assign to the model artifact that
                the file contents will be added to. This will default to the
                basename of the path prepended with the current run id if
                not specified.
            aliases: Aliases to apply to the created model artifact,
                    defaults to `["latest"]`

        Raises:
            ValueError: If name has invalid special characters.

        Returns:
            None
        """
        self._log_artifact(
            artifact_or_path=path, name=name, type="model", aliases=aliases
        )

    @_log_to_run
    @_raise_if_finished
    @_attach
    def use_model(self, name: str) -> FilePathStr:
        """Download the files logged in a model artifact 'name'.

        Args:
            name: A model artifact name. 'name' must match the name of an existing logged
                model artifact. May be prefixed with `entity/project/`. Valid names
                can be in the following forms
            - model_artifact_name:version
            - model_artifact_name:alias

        Returns:
            path (str): Path to downloaded model artifact file(s).

        Raises:
            AssertionError: If model artifact 'name' is of a type that does
                not contain the substring 'model'.
        """
        if self._settings._offline:
            # Downloading artifacts is not supported when offline.
            raise RuntimeError("`use_model` not supported in offline mode.")

        artifact = self.use_artifact(artifact_or_name=name)
        if "model" not in str(artifact.type.lower()):
            raise AssertionError(
                "You can only use this method for 'model' artifacts."
                " For an artifact to be a 'model' artifact, its type property"
                " must contain the substring 'model'."
            )

        path = artifact.download()

        # If returned directory contains only one file, return path to that file
        dir_list = os.listdir(path)
        if len(dir_list) == 1:
            return FilePathStr(os.path.join(path, dir_list[0]))
        return path

    @_log_to_run
    @_raise_if_finished
    @_attach
    def link_model(
        self,
        path: StrPath,
        registered_model_name: str,
        name: str | None = None,
        aliases: list[str] | None = None,
    ) -> Artifact | None:
        """Log a model artifact version and link it to a registered model in the model registry.

        Linked model versions are visible in the UI for the specified registered model.

        This method will:
        - Check if 'name' model artifact has been logged. If so, use the artifact version that matches the files
        located at 'path' or log a new version. Otherwise log files under 'path' as a new model artifact, 'name'
        of type 'model'.
        - Check if registered model with name 'registered_model_name' exists in the 'model-registry' project.
        If not, create a new registered model with name 'registered_model_name'.
        - Link version of model artifact 'name' to registered model, 'registered_model_name'.
        - Attach aliases from 'aliases' list to the newly linked model artifact version.

        Args:
            path: (str) A path to the contents of this model, can be in the
                following forms:
            - `/local/directory`
            - `/local/directory/file.txt`
            - `s3://bucket/path`
            registered_model_name: The name of the registered model that the
                model is to be linked to. A registered model is a collection of
                model versions linked to the model registry, typically
                representing a team's specific ML Task. The entity that this
                registered model belongs to will be derived from the run.
            name: The name of the model artifact that files in 'path' will be
                logged to. This will default to the basename of the path
                prepended with the current run id  if not specified.
            aliases: Aliases that will only be applied on this linked artifact
                inside the registered model. The alias "latest" will always be
                applied to the latest version of an artifact that is linked.

        Raises:
            AssertionError: If registered_model_name is a path or
                if model artifact 'name' is of a type that does not contain
                the substring 'model'.
            ValueError: If name has invalid special characters.

        Returns:
            The linked artifact if linking was successful, otherwise `None`.
        """
        name_parts = registered_model_name.split("/")
        if len(name_parts) != 1:
            raise AssertionError(
                "Please provide only the name of the registered model."
                " Do not append the entity or project name."
            )

        project = "model-registry"
        target_path = self.entity + "/" + project + "/" + registered_model_name

        public_api = self._public_api()
        try:
            artifact = public_api._artifact(name=f"{name}:latest")
            if "model" not in str(artifact.type.lower()):
                raise AssertionError(
                    "You can only use this method for 'model' artifacts."
                    " For an artifact to be a 'model' artifact, its type"
                    " property must contain the substring 'model'."
                )

            artifact = self._log_artifact(
                artifact_or_path=path, name=name, type=artifact.type
            )
        except (ValueError, CommError):
            artifact = self._log_artifact(
                artifact_or_path=path, name=name, type="model"
            )
        return self.link_artifact(
            artifact=artifact, target_path=target_path, aliases=aliases
        )

    @_log_to_run
    @_raise_if_finished
    @_attach
    def alert(
        self,
        title: str,
        text: str,
        level: str | AlertLevel | None = None,
        wait_duration: int | float | timedelta | None = None,
    ) -> None:
        """Create an alert with the given title and text.

        Args:
            title: The title of the alert, must be less than 64 characters long.
            text: The text body of the alert.
            level: The alert level to use, either: `INFO`, `WARN`, or `ERROR`.
            wait_duration: The time to wait (in seconds) before sending another
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
            raise TypeError(
                "wait_duration must be an int, float, or datetime.timedelta"
            )
        wait_duration = int(wait_duration.total_seconds() * 1000)

        if self._backend and self._backend.interface:
            self._backend.interface.publish_alert(title, text, level_str, wait_duration)

    def __enter__(self) -> Run:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException],
        exc_val: BaseException,
        exc_tb: TracebackType,
    ) -> bool:
        exception_raised = exc_type is not None
        if exception_raised:
            traceback.print_exception(exc_type, exc_val, exc_tb)
        exit_code = 1 if exception_raised else 0
        self._finish(exit_code=exit_code)
        return not exception_raised

    @_log_to_run
    @_raise_if_finished
    @_attach
    def mark_preempting(self) -> None:
        """Mark this run as preempting.

        Also tells the internal process to immediately report this to server.
        """
        if self._backend and self._backend.interface:
            self._backend.interface.publish_preempting()

    @property
    @_log_to_run
    @_raise_if_finished
    @_attach
    def _system_metrics(self) -> dict[str, list[tuple[datetime, float]]]:
        """Returns a dictionary of system metrics.

        Returns:
            A dictionary of system metrics.
        """
        from wandb.proto import wandb_internal_pb2

        def pb_to_dict(
            system_metrics_pb: wandb_internal_pb2.GetSystemMetricsResponse,
        ) -> dict[str, list[tuple[datetime, float]]]:
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

        try:
            result = handle.wait_or(timeout=1)
        except TimeoutError:
            return {}
        else:
            try:
                response = result.response.get_system_metrics_response
                return pb_to_dict(response) if response else {}
            except Exception:
                logger.exception("Error getting system metrics.")
                return {}

    # ------------------------------------------------------------------------------
    # HEADER
    # ------------------------------------------------------------------------------
    def _header(self) -> None:
        self._header_wandb_version_info()
        self._header_sync_info()
        self._header_run_info()

    def _header_wandb_version_info(self) -> None:
        if self._settings.quiet or self._settings.silent:
            return

        # TODO: add this to a higher verbosity level
        self._printer.display(f"Tracking run with wandb version {wandb.__version__}")

    def _header_sync_info(self) -> None:
        sync_location_msg = f"Run data is saved locally in {self._printer.files(self._settings.sync_dir)}"

        if self._settings._offline:
            offline_warning = (
                f"W&B syncing is set to {self._printer.code('`offline`')} "
                f"in this directory. Run {self._printer.code('`wandb online`')} "
                f"or set {self._printer.code('WANDB_MODE=online')} "
                "to enable cloud syncing."
            )
            self._printer.display([offline_warning, sync_location_msg])
        else:
            messages = [sync_location_msg]

            if not self._printer.supports_html:
                disable_sync_msg = (
                    f"Run {self._printer.code('`wandb offline`')} to turn off syncing."
                )
                messages.append(disable_sync_msg)

            if not self._settings.quiet and not self._settings.silent:
                self._printer.display(messages)

    def _header_run_info(self) -> None:
        settings, printer = self._settings, self._printer

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

        if printer.supports_html:
            import wandb.jupyter

            if not wandb.jupyter.display_if_magic_is_used(self):
                run_line = f"<strong>{printer.link(run_url, run_name)}</strong>"
                project_line, sweep_line = "", ""

                if not settings.quiet:
                    doc_html = printer.link(url_registry.url("developer-guide"), "docs")

                    project_html = printer.link(project_url, "Weights & Biases")
                    project_line = f"to {project_html} ({doc_html})"

                    if sweep_url:
                        sweep_line = f"Sweep page: {printer.link(sweep_url, sweep_url)}"

                printer.display(
                    [f"{run_state_str} {run_line} {project_line}", sweep_line],
                )

        elif run_name:
            printer.display(f"{run_state_str} {printer.name(run_name)}")

        if not settings.quiet:
            # TODO: add verbosity levels and add this to higher levels
            printer.display(
                f"{printer.emoji('star')} View project at {printer.link(project_url)}"
            )
            if sweep_url:
                printer.display(
                    f"{printer.emoji('broom')} View sweep at {printer.link(sweep_url)}"
                )
        printer.display(
            f"{printer.emoji('rocket')} View run at {printer.link(run_url)}",
        )

        if run_name and settings.anonymous in ["allow", "must"]:
            printer.display(
                (
                    "Do NOT share these links with anyone."
                    " They can be used to claim your runs."
                ),
                level="warn",
            )

    # ------------------------------------------------------------------------------
    # FOOTER
    # ------------------------------------------------------------------------------
    # Note: All the footer methods are static methods since we want to share the printing logic
    # with the service execution path that doesn't have access to the run instance
    @staticmethod
    def _footer(
        sampled_history: SampledHistoryResponse | None = None,
        final_summary: GetSummaryResponse | None = None,
        poll_exit_response: PollExitResponse | None = None,
        internal_messages_response: InternalMessagesResponse | None = None,
        *,
        settings: Settings,
        printer: printer.Printer,
    ) -> None:
        Run._footer_history_summary_info(
            history=sampled_history,
            summary=final_summary,
            settings=settings,
            printer=printer,
        )

        Run._footer_sync_info(
            poll_exit_response=poll_exit_response,
            settings=settings,
            printer=printer,
        )
        Run._footer_log_dir_info(settings=settings, printer=printer)
        Run._footer_internal_messages(
            internal_messages_response=internal_messages_response,
            settings=settings,
            printer=printer,
        )

    @staticmethod
    def _footer_sync_info(
        poll_exit_response: PollExitResponse | None = None,
        *,
        settings: Settings,
        printer: printer.Printer,
    ) -> None:
        if settings.silent:
            return

        if settings._offline:
            if not settings.quiet:
                printer.display(
                    [
                        "You can sync this run to the cloud by running:",
                        printer.code(f"wandb sync {settings.sync_dir}"),
                    ],
                )
            return

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
        *,
        settings: Settings,
        printer: printer.Printer,
    ) -> None:
        if settings.quiet or settings.silent:
            return

        log_dir = settings.log_user or settings.log_internal
        if log_dir:
            log_dir = os.path.dirname(log_dir.replace(os.getcwd(), "."))
            printer.display(
                f"Find logs at: {printer.files(log_dir)}",
            )

    @staticmethod
    def _footer_history_summary_info(
        history: SampledHistoryResponse | None = None,
        summary: GetSummaryResponse | None = None,
        *,
        settings: Settings,
        printer: printer.Printer,
    ) -> None:
        if settings.quiet or settings.silent:
            return

        panel: list[str] = []

        if history and (
            history_grid := Run._footer_history(history, printer, settings)
        ):
            panel.append(history_grid)

        if summary and (
            summary_grid := Run._footer_summary(summary, printer, settings)
        ):
            panel.append(summary_grid)

        if panel:
            printer.display(printer.panel(panel))

    @staticmethod
    def _footer_history(
        history: SampledHistoryResponse,
        printer: printer.Printer,
        settings: Settings,
    ) -> str | None:
        """Returns the run history formatted for printing to the console."""
        sorted_history_items = sorted(
            (item for item in history.item if not item.key.startswith("_")),
            key=lambda item: item.key,
        )

        history_rows: list[list[str]] = []
        for item in sorted_history_items:
            if len(history_rows) >= settings.max_end_of_run_history_metrics:
                break

            values = wandb.util.downsample(
                item.values_float or item.values_int,
                40,
            )

            if sparkline := printer.sparklines(values):
                history_rows.append([item.key, sparkline])

        if not history_rows:
            return None

        if len(history_rows) < len(sorted_history_items):
            remaining = len(sorted_history_items) - len(history_rows)
            history_rows.append([f"+{remaining:,d}", "..."])

        return printer.grid(history_rows, "Run history:")

    @staticmethod
    def _footer_summary(
        summary: GetSummaryResponse,
        printer: printer.Printer,
        settings: Settings,
    ) -> str | None:
        """Returns the run summary formatted for printing to the console."""
        sorted_summary_items = sorted(
            (
                item
                for item in summary.item
                if not item.key.startswith("_") and not item.nested_key
            ),
            key=lambda item: item.key,
        )

        summary_rows: list[list[str]] = []
        skipped = 0
        for item in sorted_summary_items:
            if len(summary_rows) >= settings.max_end_of_run_summary_metrics:
                break

            try:
                value = json.loads(item.value_json)
            except json.JSONDecodeError:
                logger.exception(f"Error decoding summary[{item.key!r}]")
                skipped += 1
                continue

            if isinstance(value, str):
                value = value[:20] + "..." * (len(value) >= 20)
                summary_rows.append([item.key, value])
            elif isinstance(value, numbers.Number):
                value = round(value, 5) if isinstance(value, float) else value
                summary_rows.append([item.key, str(value)])
            else:
                skipped += 1

        if not summary_rows:
            return None

        if len(summary_rows) < len(sorted_summary_items) - skipped:
            remaining = len(sorted_summary_items) - len(summary_rows) - skipped
            summary_rows.append([f"+{remaining:,d}", "..."])

        return printer.grid(summary_rows, "Run summary:")

    @staticmethod
    def _footer_internal_messages(
        internal_messages_response: InternalMessagesResponse | None = None,
        *,
        settings: Settings,
        printer: printer.Printer,
    ) -> None:
        if settings.quiet or settings.silent:
            return

        if not internal_messages_response:
            return

        for message in internal_messages_response.messages.warning:
            printer.display(message, level="warn")


# We define this outside of the run context to support restoring before init
def restore(
    name: str,
    run_path: str | None = None,
    replace: bool = False,
    root: str | None = None,
) -> None | TextIO:
    """Download the specified file from cloud storage.

    File is placed into the current directory or run directory.
    By default, will only download the file if it doesn't already exist.

    Args:
        name: The name of the file.
        run_path: Optional path to a run to pull files from, i.e. `username/project_name/run_id`
            if wandb.init has not been called, this is required.
        replace: Whether to download the file even if it already exists locally
        root: The directory to download the file to.  Defaults to the current
            directory or the run directory if wandb.init was called.

    Returns:
        None if it can't find the file, otherwise a file object open for reading.

    Raises:
        CommError: If W&B can't connect to the W&B backend.
        ValueError: If the file is not found or can't find run_path.
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


def finish(
    exit_code: int | None = None,
    quiet: bool | None = None,
) -> None:
    """Finish a run and upload any remaining data.

    Marks the completion of a W&B run and ensures all data is synced to the server.
    The run's final state is determined by its exit conditions and sync status.

    Run States:
    - Running: Active run that is logging data and/or sending heartbeats.
    - Crashed: Run that stopped sending heartbeats unexpectedly.
    - Finished: Run completed successfully (`exit_code=0`) with all data synced.
    - Failed: Run completed with errors (`exit_code!=0`).

    Args:
        exit_code: Integer indicating the run's exit status. Use 0 for success,
            any other value marks the run as failed.
        quiet: Deprecated. Configure logging verbosity using `wandb.Settings(quiet=...)`.
    """
    if wandb.run:
        wandb.run.finish(exit_code=exit_code, quiet=quiet)
