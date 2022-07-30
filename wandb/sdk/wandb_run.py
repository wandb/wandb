import _thread as thread
import atexit
from collections.abc import Mapping
from datetime import timedelta
from enum import IntEnum
import functools
import glob
import json
import logging
import numbers
import os
import re
import sys
import threading
import time
import traceback
from types import TracebackType
from typing import (
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
    TYPE_CHECKING,
    Union,
)

import requests
import wandb
from wandb import errors
from wandb import trigger
from wandb._globals import _datatypes_set_callback
from wandb.apis import internal, public
from wandb.apis.internal import Api
from wandb.apis.public import Api as PublicApi
from wandb.proto.wandb_internal_pb2 import (
    MetricRecord,
    PollExitResponse,
    RunRecord,
)
from wandb.sdk.lib.import_hooks import (
    register_post_import_hook,
    unregister_post_import_hook,
)
from wandb.util import (
    _is_artifact_object,
    _is_artifact_string,
    _is_artifact_version_weave_dict,
    _is_py_path,
    add_import_hook,
    parse_artifact_string,
    sentry_set_scope,
    to_forward_slash_path,
)
from wandb.viz import (
    custom_chart,
    CustomChart,
    Visualize,
)

from . import wandb_artifacts
from . import wandb_config
from . import wandb_metric
from . import wandb_summary
from .data_types._dtypes import TypeRegistry
from .interface.artifacts import Artifact as ArtifactInterface
from .interface.interface import GlobStr, InterfaceBase
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
from .lib.filenames import DIFF_FNAME
from .lib.git import GitRepo
from .lib.printer import get_printer
from .lib.reporting import Reporter
from .lib.wburls import wburls
from .wandb_artifacts import Artifact
from .wandb_settings import Settings, SettingsConsole
from .wandb_setup import _WandbSetup


if TYPE_CHECKING:
    if sys.version_info >= (3, 8):
        from typing import TypedDict
    else:
        from typing_extensions import TypedDict

    from .data_types.base_types.wb_value import WBValue
    from .wandb_alerts import AlertLevel

    from .interface.artifacts import (
        ArtifactEntry,
        ArtifactManifest,
    )
    from .interface.interface import FilesDict, PolicyName

    from .lib.printer import PrinterTerm, PrinterJupyter
    from wandb.proto.wandb_internal_pb2 import (
        CheckVersionResponse,
        GetSummaryResponse,
        SampledHistoryResponse,
    )

    class GitSourceDict(TypedDict):
        remote: str
        commit: str
        entrypoint: List[str]

    class ArtifactSourceDict(TypedDict):
        artifact: str
        entrypoint: List[str]

    class ImageSourceDict(TypedDict):
        image: str

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

    For now, we just use this to figure out if the user has requested a stop.
    """

    def __init__(
        self,
        interface: InterfaceBase,
        stop_polling_interval: int = 15,
        retry_polling_interval: int = 5,
    ) -> None:
        self._interface = interface
        self._stop_polling_interval = stop_polling_interval
        self._retry_polling_interval = retry_polling_interval

        self._join_event = threading.Event()

        self._stop_thread = threading.Thread(target=self.check_status)
        self._stop_thread.name = "ChkStopThr"
        self._stop_thread.daemon = True
        self._stop_thread.start()

        self._retry_thread = threading.Thread(target=self.check_network_status)
        self._retry_thread.name = "NetStatThr"
        self._retry_thread.daemon = True
        self._retry_thread.start()

    def check_network_status(self) -> None:
        join_requested = False
        while not join_requested:
            status_response = self._interface.communicate_network_status()
            if status_response and status_response.network_responses:
                for hr in status_response.network_responses:
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
            join_requested = self._join_event.wait(self._retry_polling_interval)

    def check_status(self) -> None:
        join_requested = False
        while not join_requested:
            status_response = self._interface.communicate_stop_status()
            if status_response and status_response.run_should_stop:
                # TODO(frz): This check is required
                # until WB-3606 is resolved on server side.
                if not wandb.agents.pyagent.is_running():
                    thread.interrupt_main()
                    return
            join_requested = self._join_event.wait(self._stop_polling_interval)

    def stop(self) -> None:
        self._join_event.set()

    def join(self) -> None:
        self.stop()
        self._stop_thread.join()
        self._retry_thread.join()


class _run_decorator:  # noqa: N801

    _is_attaching: str = ""

    class Dummy:
        ...

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
                    message = f"Trying to attach `{func.__name__}` while in the middle of attaching `{cls._is_attaching}`"
                    raise RuntimeError(message)
                cls._is_attaching = func.__name__
                try:
                    wandb._attach(run=self)
                except Exception as e:
                    # In case the attach fails we will raise the exception that caused the issue.
                    # This exception should be caught and fail the execution of the program.
                    cls._is_attaching = ""
                    raise e
                cls._is_attaching = ""
            return func(self, *args, **kwargs)

        return wrapper

    @classmethod
    def _noop(cls, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self: Type["Run"], *args: Any, **kwargs: Any) -> Any:
            # `_attach_id` is only assigned in service hence for all service cases
            # it will be a passthrough. We don't pickle non-service so again a way to see that we are in non-service case
            if getattr(self, "_attach_id", None) is None:
                # `_init_pid` is only assigned in __init__ (this will be constant check for mp):
                #   - for non-fork case the object is shared through pickling and we don't pickle non-service so will be None
                #   - for fork case the new process share mem space hence the value would be of parent process.
                _init_pid = getattr(self, "_init_pid", None)
                if _init_pid != os.getpid():
                    message = "`{}` ignored (called from pid={}, `init` called from pid={}). See: {}".format(
                        func.__name__,
                        os.getpid(),
                        _init_pid,
                        wburls.get("multiprocess"),
                    )
                    # - if this process was pickled in non-service case, we ignore the attributes (since pickle is not supported)
                    # - for fork case will use the settings of the parent process
                    # - only point of inconsistent behavior from forked and non-forked cases
                    settings = getattr(self, "_settings", None)
                    if settings and settings["strict"]:
                        wandb.termerror(message, repeat=False)
                        raise errors.MultiprocessError(
                            f"`{func.__name__}` does not support multiprocessing"
                        )
                    wandb.termwarn(message, repeat=False)
                    return cls.Dummy()

            return func(self, *args, **kwargs)

        return wrapper


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
    [our guide](https://docs.wandb.ai/guides/track/advanced/distributed-training).

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

    _run_obj: Optional[RunRecord]
    _run_obj_offline: Optional[RunRecord]
    # Use string literal annotation because of type reference loop
    _backend: Optional["wandb.sdk.backend.backend.Backend"]
    _internal_run_interface: Optional[
        Union[
            "wandb.sdk.interface.interface_queue.InterfaceQueue",
            "wandb.sdk.interface.interface_grpc.InterfaceGrpc",
        ]
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

    _check_version: Optional["CheckVersionResponse"]
    _sampled_history: Optional["SampledHistoryResponse"]
    _final_summary: Optional["GetSummaryResponse"]
    _poll_exit_response: Optional[PollExitResponse]

    _stdout_slave_fd: Optional[int]
    _stderr_slave_fd: Optional[int]
    _artifact_slots: List[str]

    _init_pid: int
    _attach_pid: int
    _iface_pid: Optional[int]
    _iface_port: Optional[int]

    _attach_id: Optional[str]
    _is_attached: bool
    _settings: Settings

    _launch_artifacts: Optional[Dict[str, Any]]

    def __init__(
        self,
        settings: Settings,
        config: Optional[Dict[str, Any]] = None,
        sweep_config: Optional[Dict[str, Any]] = None,
        launch_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        # pid is set, so we know if this run object was initialized by this process
        self._init_pid = os.getpid()
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
        self.summary = wandb_summary.Summary(
            self._summary_get_current_summary_callback,
        )
        self.summary._set_update_callback(self._summary_update_callback)
        self._step = 0
        self._torch_history: Optional["wandb.wandb_torch.TorchHistory"] = None

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

        self._hooks = None
        self._teardown_hooks = []
        self._out_redir = None
        self._err_redir = None
        self._stdout_slave_fd = None
        self._stderr_slave_fd = None
        self._exit_code = None
        self._exit_result = None
        self._quiet = self._settings.quiet
        self._code_artifact_info: Optional[Dict[str, str]] = None

        self._output_writer = None
        self._used_artifact_slots: Dict[str, str] = {}

        # Returned from backend request_run(), set from wandb_init?
        self._run_obj = None
        self._run_obj_offline = None

        # Created when the run "starts".
        self._run_status_checker = None

        self._check_version = None
        self._sampled_history = None
        self._final_summary = None
        self._poll_exit_response = None

        # Initialize telemetry object
        self._telemetry_obj = telemetry.TelemetryRecord()
        self._telemetry_obj_active = False
        self._telemetry_obj_flushed = b""
        self._telemetry_obj_dirty = False

        self._atexit_cleanup_called = False

        # Pull info from settings
        self._init_from_settings(self._settings)

        # Initial scope setup for sentry. This might get changed when the
        # actual run comes back.
        sentry_set_scope(
            settings_dict=self._settings,
            process_context="user",
        )

        # Populate config
        config = config or dict()
        wandb_key = "_wandb"
        config.setdefault(wandb_key, dict())
        self._launch_artifact_mapping: Dict[str, Any] = {}
        self._unique_launch_artifact_sequence_names: Dict[str, Any] = {}
        if self._settings.save_code and self._settings.program_relpath:
            config[wandb_key]["code_path"] = to_forward_slash_path(
                os.path.join("code", self._settings.program_relpath)
            )
        if sweep_config:
            self._config.update_locked(
                sweep_config, user="sweep", _allow_val_change=True
            )

        if launch_config:
            self._config.update_locked(
                launch_config, user="launch", _allow_val_change=True
            )

        self._config._update(config, ignore_locked=True)

        # interface pid and port configured when backend is configured (See _hack_set_run)
        # TODO: using pid isnt the best for windows as pid reuse can happen more often than unix
        self._iface_pid = None
        self._iface_port = None
        self._attach_id = None
        self._is_attached = False

        self._attach_pid = os.getpid()

        # for now, use runid as attach id, this could/should be versioned in the future
        if self._settings._require_service:
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
            self._save(self._settings.launch_config_path)
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
        self._telemetry_obj.MergeFrom(telem_obj)
        self._telemetry_obj_dirty = True
        self._telemetry_flush()

    def _telemetry_flush(self) -> None:
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

    def __getstate__(self) -> Any:
        """Custom pickler."""
        # We only pickle in service mode
        if not self._settings or not self._settings._require_service:
            return

        _attach_id = self._attach_id
        if not _attach_id:
            return

        return dict(_attach_id=self._attach_id, _init_pid=self._init_pid)

    def __setstate__(self, state: Any) -> None:
        """Custom unpickler."""
        if not state:
            return

        _attach_id = state.get("_attach_id")
        if not _attach_id:
            return

        if state["_init_pid"] == os.getpid():
            raise RuntimeError("attach in the same process is not supported currently")

        self.__dict__.update(state)

    @property
    def _torch(self) -> "wandb.wandb_torch.TorchHistory":
        if self._torch_history is None:
            self._torch_history = wandb.wandb_torch.TorchHistory()
        return self._torch_history

    @property  # type: ignore
    @_run_decorator._attach
    def settings(self) -> Settings:
        """Returns a frozen copy of run's Settings object."""
        cp = self._settings.copy()
        cp.freeze()
        return cp

    @property  # type: ignore
    @_run_decorator._attach
    def dir(self) -> str:
        """Returns the directory where files associated with the run are saved."""
        return self._settings.files_dir

    @property  # type: ignore
    @_run_decorator._attach
    def config(self) -> wandb_config.Config:
        """Returns the config object associated with this run."""
        return self._config

    @property  # type: ignore
    @_run_decorator._attach
    def config_static(self) -> wandb_config.ConfigStatic:
        return wandb_config.ConfigStatic(self._config)

    @property  # type: ignore
    @_run_decorator._attach
    def name(self) -> Optional[str]:
        """Returns the display name of the run.

        Display names are not guaranteed to be unique and may be descriptive.
        By default, they are randomly generated.
        """
        if self._name:
            return self._name
        if not self._run_obj:
            return None
        return self._run_obj.display_name

    @name.setter
    def name(self, name: str) -> None:
        with telemetry.context(run=self) as tel:
            tel.feature.set_run_name = True
        self._name = name
        if self._backend and self._backend.interface:
            self._backend.interface.publish_run(self)

    @property  # type: ignore
    @_run_decorator._attach
    def notes(self) -> Optional[str]:
        """Returns the notes associated with the run, if there are any.

        Notes can be a multiline string and can also use markdown and latex equations
        inside `$$`, like `$x + 3$`.
        """
        if self._notes:
            return self._notes
        if not self._run_obj:
            return None
        return self._run_obj.notes

    @notes.setter
    def notes(self, notes: str) -> None:
        self._notes = notes
        if self._backend and self._backend.interface:
            self._backend.interface.publish_run(self)

    @property  # type: ignore
    @_run_decorator._attach
    def tags(self) -> Optional[Tuple]:
        """Returns the tags associated with the run, if there are any."""
        if self._tags:
            return self._tags
        run_obj = self._run_obj or self._run_obj_offline
        if run_obj:
            return tuple(run_obj.tags)
        return None

    @tags.setter
    def tags(self, tags: Sequence) -> None:
        with telemetry.context(run=self) as tel:
            tel.feature.set_run_tags = True
        self._tags = tuple(tags)
        if self._backend and self._backend.interface:
            self._backend.interface.publish_run(self)

    @property  # type: ignore
    @_run_decorator._attach
    def id(self) -> str:
        """Returns the identifier for this run."""
        if TYPE_CHECKING:
            assert self._run_id is not None
        return self._run_id

    @property  # type: ignore
    @_run_decorator._attach
    def sweep_id(self) -> Optional[str]:
        """Returns the ID of the sweep associated with the run, if there is one."""
        if not self._run_obj:
            return None
        return self._run_obj.sweep_id or None

    def _get_path(self) -> str:
        parts = [
            e for e in [self._entity, self._project, self._run_id] if e is not None
        ]
        return "/".join(parts)

    @property  # type: ignore
    @_run_decorator._attach
    def path(self) -> str:
        """Returns the path to the run.

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

    @property  # type: ignore
    @_run_decorator._attach
    def start_time(self) -> float:
        """Returns the unix time stamp, in seconds, when the run started."""
        return self._get_start_time()

    def _get_starting_step(self) -> int:
        return self._starting_step if not self._run_obj else self._run_obj.starting_step

    @property  # type: ignore
    @_run_decorator._attach
    def starting_step(self) -> int:
        """Returns the first step of the run."""
        return self._get_starting_step()

    @property  # type: ignore
    @_run_decorator._attach
    def resumed(self) -> bool:
        """Returns True if the run was resumed, False otherwise."""
        return self._run_obj.resumed if self._run_obj else False

    @property  # type: ignore
    @_run_decorator._attach
    def step(self) -> int:
        """Returns the current value of the step.

        This counter is incremented by `wandb.log`.
        """
        return self._step

    def project_name(self) -> str:
        run_obj = self._run_obj or self._run_obj_offline
        return run_obj.project if run_obj else ""

    @property  # type: ignore
    @_run_decorator._attach
    def mode(self) -> str:
        """For compatibility with `0.9.x` and earlier, deprecate eventually."""
        deprecate.deprecate(
            field_name=deprecate.Deprecated.run__mode,
            warning_message=(
                "The mode property of wandb.run is deprecated "
                "and will be removed in a future release."
            ),
        )
        return "dryrun" if self._settings._offline else "run"

    @property  # type: ignore
    @_run_decorator._attach
    def offline(self) -> bool:
        return self._settings._offline

    @property  # type: ignore
    @_run_decorator._attach
    def disabled(self) -> bool:
        return self._settings._noop

    def _get_group(self) -> str:
        run_obj = self._run_obj or self._run_obj_offline
        return run_obj.run_group if run_obj else ""

    @property  # type: ignore
    @_run_decorator._attach
    def group(self) -> str:
        """Returns the name of the group associated with the run.

        Setting a group helps the W&B UI organize runs in a sensible way.

        If you are doing a distributed training you should give all of the
            runs in the training the same group.
        If you are doing crossvalidation you should give all the crossvalidation
            folds the same group.
        """
        return self._get_group()

    @property  # type: ignore
    @_run_decorator._attach
    def job_type(self) -> str:
        run_obj = self._run_obj or self._run_obj_offline
        return run_obj.job_type if run_obj else ""

    @property  # type: ignore
    @_run_decorator._attach
    def project(self) -> str:
        """Returns the name of the W&B project associated with the run."""
        return self.project_name()

    @_run_decorator._attach
    def log_code(
        self,
        root: str = ".",
        name: str = None,
        include_fn: Callable[[str], bool] = _is_py_path,
        exclude_fn: Callable[[str], bool] = filenames.exclude_wandb_fn,
    ) -> Optional[Artifact]:
        """Saves the current state of your code to a W&B Artifact.

        By default, it walks the current directory and logs all files that end with `.py`.

        Arguments:
            root: The relative (to `os.getcwd()`) or absolute path to recursively find code from.
            name: (str, optional) The name of our code artifact. By default, we'll name
                the artifact `source-$PROJECT_ID-$ENTRYPOINT_RELPATH`. There may be scenarios where you want
                many runs to share the same artifact. Specifying name allows you to achieve that.
            include_fn: A callable that accepts a file path and
                returns True when it should be included and False otherwise. This
                defaults to: `lambda path: path.endswith(".py")`
            exclude_fn: A callable that accepts a file path and returns `True` when it should be
                excluded and `False` otherwise. This defaults to: `lambda path: False`

        Examples:
            Basic usage
            ```python
            run.log_code()
            ```

            Advanced usage
            ```python
            run.log_code(
                "../", include_fn=lambda path: path.endswith(".py") or path.endswith(".ipynb")
            )
            ```

        Returns:
            An `Artifact` object if code was logged
        """
        if name is None:
            name_string = wandb.util.make_artifact_name_safe(
                f"{self._project}-{self._settings.program_relpath}"
            )
            name = f"source-{name_string}"
        art = wandb.Artifact(name, "code")
        files_added = False
        if root is not None:
            root = os.path.abspath(root)
            for file_path in filenames.filtered_dir(root, include_fn, exclude_fn):
                files_added = True
                save_name = os.path.relpath(file_path, root)
                art.add_file(file_path, name=save_name)
        # Add any manually staged files such is ipynb notebooks
        for dirpath, _, files in os.walk(self._settings._tmp_code_dir):
            for fname in files:
                file_path = os.path.join(dirpath, fname)
                save_name = os.path.relpath(file_path, self._settings._tmp_code_dir)
                files_added = True
                art.add_file(file_path, name=save_name)
        if not files_added:
            return None
        self._code_artifact_info = {"name": name, "client_id": art._client_id}

        return self._log_artifact(art)

    def get_url(self) -> Optional[str]:
        """Returns the url for the W&B run, if there is one.

        Offline runs will not have a url.
        """
        if self._settings._offline:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._settings.run_url

    def get_project_url(self) -> Optional[str]:
        """Returns the url for the W&B project associated with the run, if there is one.

        Offline runs will not have a project url.
        """
        if self._settings._offline:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._settings.project_url

    def get_sweep_url(self) -> Optional[str]:
        """Returns the url for the sweep associated with the run, if there is one."""
        if self._settings._offline:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._settings.sweep_url

    @property  # type: ignore
    @_run_decorator._attach
    def url(self) -> Optional[str]:
        """Returns the W&B url associated with the run."""
        return self.get_url()

    @property  # type: ignore
    @_run_decorator._attach
    def entity(self) -> str:
        """Returns the name of the W&B entity associated with the run.

        Entity can be a user name or the name of a team or organization.
        """
        return self._entity or ""

    def _label_internal(
        self, code: str = None, repo: str = None, code_version: str = None
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
        code: str = None,
        repo: str = None,
        code_version: str = None,
        **kwargs: str,
    ) -> None:
        if self._settings.label_disable:
            return
        for k, v in (("code", code), ("repo", repo), ("code_version", code_version)):
            if v and not RE_LABEL.match(v):
                wandb.termwarn(
                    "Label added for '{}' with invalid identifier '{}' (ignored).".format(
                        k, v
                    ),
                    repeat=False,
                )
        for v in kwargs:
            wandb.termwarn(
                f"Label added for unsupported key '{v}' (ignored).",
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
        """Displays this run in jupyter."""
        if self._settings._jupyter and ipython.in_jupyter():
            ipython.display_html(self.to_html(height, hidden))
            return True
        else:
            wandb.termwarn(".display() only works in jupyter environments")
            return False

    @_run_decorator._attach
    def to_html(self, height: int = 420, hidden: bool = False) -> str:
        """Generates HTML containing an iframe displaying the current run."""
        url = self._settings.run_url + "?jupyter=true"
        style = f"border:none;width:100%;height:{height}px;"
        prefix = ""
        if hidden:
            style += "display:none;"
            prefix = ipython.toggle_button()
        return prefix + f'<iframe src="{url}" style="{style}"></iframe>'

    def _repr_mimebundle_(
        self, include: Any = None, exclude: Any = None
    ) -> Dict[str, str]:
        return {"text/html": self.to_html(hidden=True)}

    def _config_callback(
        self,
        key: Union[Tuple[str, ...], str] = None,
        val: Any = None,
        data: Dict[str, object] = None,
    ) -> None:
        logger.info(f"config_cb {key} {val} {data}")
        if self._backend and self._backend.interface:
            self._backend.interface.publish_config(key=key, val=val, data=data)

    def _config_artifact_callback(
        self, key: str, val: Union[str, Artifact, dict]
    ) -> Union[Artifact, public.Artifact]:
        # artifacts can look like dicts as they are passed into the run config
        # since the run config stores them on the backend as a dict with fields shown
        # in wandb.util.artifact_to_json
        if _is_artifact_version_weave_dict(val):
            assert isinstance(val, dict)
            public_api = self._public_api()
            artifact = public.Artifact.from_id(val["id"], public_api.client)
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
                artifact = public.Artifact.from_id(artifact_string, public_api._client)
            else:
                artifact = public_api.artifact(name=artifact_string)
            # in the future we'll need to support using artifacts from
            # different instances of wandb. simplest way to do that is
            # likely to convert the retrieved public.Artifact to a wandb.Artifact

            return self.use_artifact(artifact, use_as=key)
        elif _is_artifact_object(val):
            return self.use_artifact(val, use_as=key)
        else:
            raise ValueError(
                f"Cannot call _config_artifact_callback on type {type(val)}"
            )

    def _set_config_wandb(self, key: str, val: Any) -> None:
        self._config_callback(key=("_wandb", key), val=val)

    def _summary_update_callback(self, summary_record: SummaryRecord) -> None:
        if self._backend and self._backend.interface:
            self._backend.interface.publish_summary(summary_record)

    def _summary_get_current_summary_callback(self) -> Dict[str, Any]:
        if not self._backend or not self._backend.interface:
            return {}
        ret = self._backend.interface.communicate_get_summary()
        if not ret:
            return {}
        return proto_util.dict_from_proto_list(ret.item)

    def _metric_callback(self, metric_record: MetricRecord) -> None:
        if self._backend and self._backend.interface:
            self._backend.interface._publish_metric(metric_record)

    def _datatypes_callback(self, fname: str) -> None:
        if not self._backend or not self._backend.interface:
            return
        files: "FilesDict" = dict(files=[(GlobStr(glob.escape(fname)), "now")])
        self._backend.interface.publish_files(files)

    def _visualization_hack(self, row: Dict[str, Any]) -> Dict[str, Any]:
        # TODO(jhr): move visualize hack somewhere else
        chart_keys = set()
        for k in row:
            if isinstance(row[k], Visualize):
                key = row[k].get_config_key(k)
                value = row[k].get_config_value(k)
                row[k] = row[k]._data
                self._config_callback(val=value, key=key)
            elif isinstance(row[k], CustomChart):
                chart_keys.add(k)
                key = row[k].get_config_key(k)
                value = row[k].get_config_value(
                    "Vega2", row[k].user_query(f"{k}_table")
                )
                row[k] = row[k]._data
                self._config_callback(val=value, key=key)

        for k in chart_keys:
            # remove the chart key from the row
            # TODO: is this really the right move? what if the user logs
            #     a non-custom chart to this key?
            row[f"{k}_table"] = row.pop(k)
        return row

    def _partial_history_callback(
        self,
        row: Dict[str, Any],
        step: Optional[int] = None,
        commit: Optional[bool] = None,
    ) -> None:
        if row:
            row = self._visualization_hack(row)
            now = time.time()
            row["_timestamp"] = row.get("_timestamp", now)
            row["_runtime"] = row.get("_runtime", now - self._get_start_time())

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

    def _console_raw_callback(self, name: str, data: str) -> None:
        # logger.info("console callback: %s, %s", name, data)
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
        interface: Union[
            "wandb.sdk.interface.interface_queue.InterfaceQueue",
            "wandb.sdk.interface.interface_grpc.InterfaceGrpc",
        ],
    ) -> None:
        self._internal_run_interface = interface

    def _set_reporter(self, reporter: Reporter) -> None:
        self._reporter = reporter

    def _set_teardown_hooks(self, hooks: List[TeardownHook]) -> None:
        self._teardown_hooks = hooks

    def _set_run_obj(self, run_obj: RunRecord) -> None:
        self._run_obj = run_obj
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
            self.summary.update(summary_dict)
        self._step = self._get_starting_step()
        # TODO: It feels weird to call this twice..
        sentry_set_scope(
            process_context="user",
            settings_dict=self._settings,
        )

    def _set_run_obj_offline(self, run_obj: RunRecord) -> None:
        self._run_obj_offline = run_obj

    def _add_singleton(
        self, data_type: str, key: str, value: Dict[Union[int, str], str]
    ) -> None:
        """Stores a singleton item to wandb config.

        A singleton in this context is a piece of data that is continually
        logged with the same value in each history step, but represented
        as a single item in the config.

        We do this to avoid filling up history with a lot of repeated uneccessary data

        Add singleton can be called many times in one run and it will only be
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
                    "Note that setting step in multiprocessing can result in data loss. Please log your step values as a metric such as 'global_step'",
                    repeat=False,
                )
            # if step is passed in when tensorboard_sync is used we honor the step passed
            # to make decisions about how to close out the history record, but will strip
            # this history later on in publish_history()
            if len(wandb.patched["tensorboard"]) > 0:
                wandb.termwarn(
                    "Step cannot be set when using syncing with tensorboard. Please log your step values as a metric such as 'global_step'",
                    repeat=False,
                )
            if step > self._step:
                self._step = step

        if (step is None and commit is None) or commit:
            self._step += 1

    @_run_decorator._noop
    @_run_decorator._attach
    def log(
        self,
        data: Dict[str, Any],
        step: Optional[int] = None,
        commit: Optional[bool] = None,
        sync: Optional[bool] = None,
    ) -> None:
        """Logs a dictonary of data to the current run's history.

        Use `wandb.log` to log data from runs, such as scalars, images, video,
        histograms, plots, and tables.

        See our [guides to logging](https://docs.wandb.ai/guides/track/log) for
        live examples, code snippets, best practices, and more.

        The most basic usage is `wandb.log({"train-loss": 0.5, "accuracy": 0.9})`.
        This will save the loss and accuracy to the run's history and update
        the summary values for these metrics.

        Visualize logged data in the workspace at [wandb.ai](https://wandb.ai),
        or locally on a [self-hosted instance](https://docs.wandb.ai/self-hosted)
        of the W&B app, or export data to visualize and explore locally, e.g. in
        Jupyter notebooks, with [our API](https://docs.wandb.ai/guides/track/public-api-guide).

        In the UI, summary values show up in the run table to compare single values across runs.
        Summary values can also be set directly with `wandb.run.summary["key"] = value`.

        Logged values don't have to be scalars. Logging any wandb object is supported.
        For example `wandb.log({"example": wandb.Image("myimage.jpg")})` will log an
        example image which will be displayed nicely in the W&B UI.
        See the [reference documentation](https://docs.wandb.com/library/reference/data_types)
        for all of the different supported types or check out our
        [guides to logging](https://docs.wandb.ai/guides/track/log) for examples,
        from 3D molecular structures and segmentation masks to PR curves and histograms.
        `wandb.Table`s can be used to logged structured data. See our
        [guide to logging tables](https://docs.wandb.ai/guides/data-vis/log-tables)
        for details.

        Logging nested metrics is encouraged and is supported in the W&B UI.
        If you log with a nested dictionary like `wandb.log({"train":
        {"acc": 0.9}, "val": {"acc": 0.8}})`, the metrics will be organized into
        `train` and `val` sections in the W&B UI.

        wandb keeps track of a global step, which by default increments with each
        call to `wandb.log`, so logging related metrics together is encouraged.
        If it's inconvenient to log related metrics together
        calling `wandb.log({"train-loss": 0.5}, commit=False)` and then
        `wandb.log({"accuracy": 0.9})` is equivalent to calling
        `wandb.log({"train-loss": 0.5, "accuracy": 0.9})`.

        `wandb.log` is not intended to be called more than a few times per second.
        If you want to log more frequently than that it's better to aggregate
        the data on the client side or you may get degraded performance.

        Arguments:
            data: (dict, optional) A dict of serializable python objects i.e `str`,
                `ints`, `floats`, `Tensors`, `dicts`, or any of the `wandb.data_types`.
            commit: (boolean, optional) Save the metrics dict to the wandb server
                and increment the step.  If false `wandb.log` just updates the current
                metrics dict with the data argument and metrics won't be saved until
                `wandb.log` is called with `commit=True`.
            step: (integer, optional) The global step in processing. This persists
                any non-committed earlier steps but defaults to not committing the
                specified step.
            sync: (boolean, True) This argument is deprecated and currently doesn't
                change the behaviour of `wandb.log`.

        Examples:
            For more and more detailed examples, see
            [our guides to logging](https://docs.wandb.com/guides/track/log).

            ### Basic usage
            <!--yeadoc-test:init-and-log-basic-->
            ```python
            import wandb

            wandb.init()
            wandb.log({"accuracy": 0.9, "epoch": 5})
            ```

            ### Incremental logging
            <!--yeadoc-test:init-and-log-incremental-->
            ```python
            import wandb

            wandb.init()
            wandb.log({"loss": 0.2}, commit=False)
            # Somewhere else when I'm ready to report this step:
            wandb.log({"accuracy": 0.8})
            ```

            ### Histogram
            <!--yeadoc-test:init-and-log-histogram-->
            ```python
            import numpy as np
            import wandb

            # sample gradients at random from normal distribution
            gradients = np.random.randn(100, 100)
            wandb.init()
            wandb.log({"gradients": wandb.Histogram(gradients)})
            ```

            ### Image from numpy
            <!--yeadoc-test:init-and-log-image-numpy-->
            ```python
            import numpy as np
            import wandb

            wandb.init()
            examples = []
            for i in range(3):
                pixels = np.random.randint(low=0, high=256, size=(100, 100, 3))
                image = wandb.Image(pixels, caption=f"random field {i}")
                examples.append(image)
            wandb.log({"examples": examples})
            ```

            ### Image from PIL
            <!--yeadoc-test:init-and-log-image-pillow-->
            ```python
            import numpy as np
            from PIL import Image as PILImage
            import wandb

            wandb.init()
            examples = []
            for i in range(3):
                pixels = np.random.randint(low=0, high=256, size=(100, 100, 3), dtype=np.uint8)
                pil_image = PILImage.fromarray(pixels, mode="RGB")
                image = wandb.Image(pil_image, caption=f"random field {i}")
                examples.append(image)
            wandb.log({"examples": examples})
            ```

            ### Video from numpy
            <!--yeadoc-test:init-and-log-video-numpy-->
            ```python
            import numpy as np
            import wandb

            wandb.init()
            # axes are (time, channel, height, width)
            frames = np.random.randint(low=0, high=256, size=(10, 3, 100, 100), dtype=np.uint8)
            wandb.log({"video": wandb.Video(frames, fps=4)})
            ```

            ### Matplotlib Plot
            <!--yeadoc-test:init-and-log-matplotlib-->
            ```python
            from matplotlib import pyplot as plt
            import numpy as np
            import wandb

            wandb.init()
            fig, ax = plt.subplots()
            x = np.linspace(0, 10)
            y = x * x
            ax.plot(x, y)  # plot y = x^2
            wandb.log({"chart": fig})
            ```

            ### PR Curve
            ```python
            wandb.log({"pr": wandb.plots.precision_recall(y_test, y_probas, labels)})
            ```

            ### 3D Object
            ```python
            wandb.log(
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
        if sync is not None:
            deprecate.deprecate(
                field_name=deprecate.Deprecated.run__log_sync,
                warning_message=(
                    "`sync` argument is deprecated and does not affect the behaviour of `wandb.log`"
                ),
            )
        self._log(data=data, step=step, commit=commit)

    @_run_decorator._attach
    def save(
        self,
        glob_str: Optional[str] = None,
        base_path: Optional[str] = None,
        policy: "PolicyName" = "live",
    ) -> Union[bool, List[str]]:
        """Ensure all files matching `glob_str` are synced to wandb with the policy specified.

        Arguments:
            glob_str: (string) a relative or absolute path to a unix glob or regular
                path.  If this isn't specified the method is a noop.
            base_path: (string) the base path to run the glob relative to
            policy: (string) on of `live`, `now`, or `end`
                - live: upload the file as it changes, overwriting the previous version
                - now: upload the file once now
                - end: only upload file when the run ends
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

        return self._save(glob_str, base_path, policy)

    def _save(
        self,
        glob_str: Optional[str] = None,
        base_path: Optional[str] = None,
        policy: "PolicyName" = "live",
    ) -> Union[bool, List[str]]:

        if policy not in ("live", "end", "now"):
            raise ValueError(
                'Only "live" "end" and "now" policies are currently supported.'
            )
        if isinstance(glob_str, bytes):
            glob_str = glob_str.decode("utf-8")
        if not isinstance(glob_str, str):
            raise ValueError("Must call wandb.save(glob_str) with glob_str a str")

        if base_path is None:
            if os.path.isabs(glob_str):
                base_path = os.path.dirname(glob_str)
                wandb.termwarn(
                    "Saving files without folders. If you want to preserve "
                    "sub directories pass base_path to wandb.save, i.e. "
                    'wandb.save("/mnt/folder/file.h5", base_path="/mnt")'
                )
            else:
                base_path = "."
        wandb_glob_str = GlobStr(os.path.relpath(glob_str, base_path))
        if ".." + os.sep in wandb_glob_str:
            raise ValueError("globs can't walk above base_path")

        with telemetry.context(run=self) as tel:
            tel.feature.save = True

        if glob_str.startswith("gs://") or glob_str.startswith("s3://"):
            wandb.termlog(
                "%s is a cloud storage url, can't save file to wandb." % glob_str
            )
            return []
        files = glob.glob(os.path.join(self._settings.files_dir, wandb_glob_str))
        warn = False
        if len(files) == 0 and "*" in wandb_glob_str:
            warn = True
        for path in glob.glob(glob_str):
            file_name = os.path.relpath(path, base_path)
            abs_path = os.path.abspath(path)
            wandb_path = os.path.join(self._settings.files_dir, file_name)
            wandb.util.mkdir_exists_ok(os.path.dirname(wandb_path))
            # We overwrite symlinks because namespaces can change in Tensorboard
            if os.path.islink(wandb_path) and abs_path != os.readlink(wandb_path):
                os.remove(wandb_path)
                os.symlink(abs_path, wandb_path)
            elif not os.path.exists(wandb_path):
                os.symlink(abs_path, wandb_path)
            files.append(wandb_path)
        if warn:
            file_str = "%i file" % len(files)
            if len(files) > 1:
                file_str += "s"
            wandb.termwarn(
                (
                    "Symlinked %s into the W&B run directory, "
                    "call wandb.save again to sync new files."
                )
                % file_str
            )
        files_dict: "FilesDict" = dict(files=[(wandb_glob_str, policy)])
        if self._backend and self._backend.interface:
            self._backend.interface.publish_files(files_dict)
        return files

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
    def finish(self, exit_code: int = None, quiet: Optional[bool] = None) -> None:
        """Marks a run as finished, and finishes uploading all data.

        This is used when creating multiple runs in the same process. We automatically
        call this method when your script exits or if you use the run context manager.

        Arguments:
            exit_code: Set to something other than 0 to mark a run as failed
            quiet: Set to true to minimize log output
        """
        return self._finish(exit_code, quiet)

    def _finish(self, exit_code: int = None, quiet: Optional[bool] = None) -> None:
        if quiet is not None:
            self._quiet = quiet
        with telemetry.context(run=self) as tel:
            tel.feature.finish = True
        logger.info(f"finishing run {self._get_path()}")
        # detach jupyter hooks / others that needs to happen before backend shutdown
        for hook in self._teardown_hooks:
            if hook.stage == TeardownStage.EARLY:
                hook.call()

        self._atexit_cleanup(exit_code=exit_code)
        if self._wl and len(self._wl._global_run_stack) > 0:
            self._wl._global_run_stack.pop()
        # detach logger / others meant to be run after we've shutdown the backend
        for hook in self._teardown_hooks:
            if hook.stage == TeardownStage.LATE:
                hook.call()
        self._teardown_hooks = []
        module.unset_globals()

        # inform manager this run is finished
        manager = self._wl and self._wl._get_manager()
        if manager:
            manager._inform_finish(run_id=self._run_id)

    @_run_decorator._noop
    @_run_decorator._attach
    def join(self, exit_code: int = None) -> None:
        """Deprecated alias for `finish()` - please use finish."""
        deprecate.deprecate(
            field_name=deprecate.Deprecated.run__join,
            warning_message=(
                "wandb.run.join() is deprecated, please use wandb.run.finish()."
            ),
        )
        self._finish(exit_code=exit_code)

    @staticmethod
    def plot_table(
        vega_spec_name: str,
        data_table: "wandb.Table",
        fields: Dict[str, Any],
        string_fields: Optional[Dict[str, Any]] = None,
    ) -> CustomChart:
        """Creates a custom plot on a table.

        Arguments:
            vega_spec_name: the name of the spec for the plot
            table_key: the key used to log the data table
            data_table: a wandb.Table object containing the data to
                be used on the visualization
            fields: a dict mapping from table keys to fields that the custom
                visualization needs
            string_fields: a dict that provides values for any string constants
                the custom visualization needs
        """
        return custom_chart(vega_spec_name, data_table, fields, string_fields or {})

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
        )

    def _redirect(
        self,
        stdout_slave_fd: Optional[int],
        stderr_slave_fd: Optional[int],
        console: SettingsConsole = None,
    ) -> None:
        if console is None:
            console = self._settings._console
        # only use raw for service to minimize potential changes
        if console == SettingsConsole.WRAP:
            if self._settings._require_service:
                console = SettingsConsole.WRAP_RAW
            else:
                console = SettingsConsole.WRAP_EMU
        logger.info("redirect: %s", console)

        out_redir: redirect.RedirectBase
        err_redir: redirect.RedirectBase

        # raw output handles the output_log writing in the internal process
        if console in {SettingsConsole.REDIRECT, SettingsConsole.WRAP_EMU}:
            output_log_path = os.path.join(
                self._settings.files_dir, filenames.OUTPUT_FNAME
            )
            # output writer might have been setup, see wrap_fallback case
            if not self._output_writer:
                self._output_writer = filesystem.CRDedupedFile(
                    open(output_log_path, "wb")
                )

        if console == SettingsConsole.REDIRECT:
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
                    self._redirect(None, None, console=SettingsConsole.WRAP)

                add_import_hook("tensorflow", wrap_fallback)
        elif console == SettingsConsole.WRAP_EMU:
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
        elif console == SettingsConsole.WRAP_RAW:
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
        elif console == SettingsConsole.OFF:
            return
        else:
            raise ValueError("unhandled console")
        try:
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

    def _atexit_cleanup(self, exit_code: int = None) -> None:
        if self._backend is None:
            logger.warning("process exited without backend configured")
            return
        if self._atexit_cleanup_called:
            return
        self._atexit_cleanup_called = True

        exit_code = exit_code or self._hooks.exit_code if self._hooks else 0
        logger.info(f"got exitcode: {exit_code}")
        if exit_code == 0:
            # Cleanup our resume file on a clean exit
            if os.path.exists(self._settings.resume_fname):
                os.remove(self._settings.resume_fname)

        self._exit_code = exit_code
        report_failure = False
        try:
            self._on_finish()
        except KeyboardInterrupt as ki:
            if wandb.wandb_agent._is_running():
                raise ki
            wandb.termerror("Control-C detected -- Run data was not synced")
            if not self._settings._jupyter:
                os._exit(-1)
        except Exception as e:
            if not self._settings._jupyter:
                report_failure = True
            self._console_stop()
            self._backend.cleanup()
            logger.error("Problem finishing run", exc_info=e)
            wandb.termerror("Problem finishing run")
            traceback.print_exception(*sys.exc_info())
        else:
            self._on_final()
        finally:
            if report_failure:
                os._exit(-1)

    def _console_start(self) -> None:
        logger.info("atexit reg")
        self._hooks = ExitHooks()

        manager = self._wl and self._wl._get_manager()
        if not manager:
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

        if self._backend and self._backend.interface:
            logger.info("communicating current version")
            self._check_version = self._backend.interface.communicate_check_version(
                current_version=wandb.__version__
            )
        logger.info(f"got version response {self._check_version}")

    def _on_start(self) -> None:
        # would like to move _set_global to _on_ready to unify _on_start and _on_attach (we want to do the set globals after attach)
        # TODO(console) However _console_start calls Redirect that uses `wandb.run` hence breaks
        # TODO(jupyter) However _header calls _header_run_info that uses wandb.jupyter that uses `wandb.run` and hence breaks
        self._set_globals()
        self._header(
            self._check_version, settings=self._settings, printer=self._printer
        )

        if self._settings.save_code and self._settings.code_dir is not None:
            self.log_code(self._settings.code_dir)

        # TODO(wandb-service) RunStatusChecker not supported yet (WB-7352)
        if self._backend and self._backend.interface and not self._settings._offline:
            self._run_status_checker = RunStatusChecker(self._backend.interface)

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

        # object is about to be returned to the user, don't let them modify it
        self._freeze()

    def _log_job(self) -> None:
        artifact = None
        input_types = TypeRegistry.type_of(self.config.as_dict()).to_json()
        output_types = TypeRegistry.type_of(self.summary._as_dict()).to_json()

        import pkg_resources

        installed_packages_list = sorted(
            f"{d.key}=={d.version}" for d in iter(pkg_resources.working_set)
        )

        for job_creation_function in [
            self._create_repo_job,
            self._create_artifact_job,
            self._create_image_job,
        ]:
            artifact = job_creation_function(
                input_types, output_types, installed_packages_list
            )
            if artifact:
                break
            else:
                logger.info(
                    f"Failed to create job using {job_creation_function.__name__}"
                )

    def _construct_job_artifact(
        self,
        name: str,
        source_dict: "JobSourceDict",
        installed_packages_list: List[str],
        patch_path: Optional[os.PathLike] = None,
    ) -> "Artifact":
        job_artifact = wandb.Artifact(name, type="job")
        if patch_path and os.path.exists(patch_path):
            job_artifact.add_file(patch_path, "diff.patch")
        with job_artifact.new_file("requirements.frozen.txt") as f:
            f.write("\n".join(installed_packages_list))
        with job_artifact.new_file("wandb-job.json") as f:
            f.write(json.dumps(source_dict))

        return job_artifact

    def _create_repo_job(
        self,
        input_types: Dict[str, Any],
        output_types: Dict[str, Any],
        installed_packages_list: List[str],
    ) -> "Optional[Artifact]":
        """Create a job version artifact from a repo."""
        has_repo = self._remote_url is not None and self._commit is not None
        program_relpath = self._settings.program_relpath
        if not has_repo or program_relpath is None:
            return None
        assert self._remote_url is not None
        assert self._commit is not None
        name = wandb.util.make_artifact_name_safe(
            f"job-{self._remote_url}_{program_relpath}"
        )
        patch_path = os.path.join(self._settings.files_dir, DIFF_FNAME)

        source_info: JobSourceDict = {
            "_version": "v0",
            "source_type": "repo",
            "source": {
                "git": {
                    "remote": self._remote_url,
                    "commit": self._commit,
                },
                "entrypoint": [
                    sys.executable.split("/")[-1],
                    program_relpath,
                ],
            },
            "input_types": input_types,
            "output_types": output_types,
            "runtime": self._settings._python,
        }

        job_artifact = self._construct_job_artifact(
            name, source_info, installed_packages_list, patch_path
        )
        artifact = self.log_artifact(job_artifact)
        return artifact

    def _create_artifact_job(
        self,
        input_types: Dict[str, Any],
        output_types: Dict[str, Any],
        installed_packages_list: List[str],
    ) -> "Optional[Artifact]":
        if (
            self._code_artifact_info is None
            or self._run_obj is None
            or self._settings.program_relpath is None
        ):
            return None
        artifact_client_id = self._code_artifact_info.get("client_id")
        name = f"job-{self._code_artifact_info['name']}"

        source_info: JobSourceDict = {
            "_version": "v0",
            "source_type": "artifact",
            "source": {
                "artifact": f"wandb-artifact://_id/{artifact_client_id}",
                "entrypoint": [
                    sys.executable.split("/")[-1],
                    self._settings.program_relpath,
                ],
            },
            "input_types": input_types,
            "output_types": output_types,
            "runtime": self._settings._python,
        }
        job_artifact = self._construct_job_artifact(
            name, source_info, installed_packages_list
        )
        artifact = self.log_artifact(job_artifact)
        return artifact

    def _create_image_job(
        self,
        input_types: Dict[str, Any],
        output_types: Dict[str, Any],
        installed_packages_list: List[str],
    ) -> "Optional[Artifact]":
        docker_image_name = os.getenv("WANDB_DOCKER")
        if docker_image_name is None:
            return None
        name = wandb.util.make_artifact_name_safe(f"job-{docker_image_name}")

        source_info: JobSourceDict = {
            "_version": "v0",
            "source_type": "image",
            "source": {"image": docker_image_name},
            "input_types": input_types,
            "output_types": output_types,
            "runtime": self._settings._python,
        }
        job_artifact = self._construct_job_artifact(
            name, source_info, installed_packages_list
        )
        artifact = self.log_artifact(job_artifact)
        return artifact

    def _on_finish(self) -> None:
        trigger.call("on_finished")

        if self._run_status_checker:
            self._run_status_checker.stop()

        if not self._settings._offline and self._settings.enable_job_creation:
            self._log_job()

        self._console_stop()  # TODO: there's a race here with jupyter console logging

        if self._backend and self._backend.interface:
            # TODO: we need to handle catastrophic failure better
            # some tests were timing out on sending exit for reasons not clear to me
            self._backend.interface.publish_exit(self._exit_code)

        self._footer_exit_status_info(
            self._exit_code, settings=self._settings, printer=self._printer
        )

        while not (self._poll_exit_response and self._poll_exit_response.done):
            if self._backend and self._backend.interface:
                self._poll_exit_response = (
                    self._backend.interface.communicate_poll_exit()
                )
                logger.info(f"got exit ret: {self._poll_exit_response}")
                self._footer_file_pusher_status_info(
                    self._poll_exit_response,
                    printer=self._printer,
                )
            time.sleep(0.1)

        if self._backend and self._backend.interface:
            self._sampled_history = (
                self._backend.interface.communicate_sampled_history()
            )
            self._final_summary = self._backend.interface.communicate_get_summary()

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

    def _on_final(self) -> None:
        self._footer(
            self._sampled_history,
            self._final_summary,
            self._poll_exit_response,
            self._check_version,
            self._reporter,
            self._quiet,
            settings=self._settings,
            printer=self._printer,
        )

    @_run_decorator._attach
    def define_metric(
        self,
        name: str,
        step_metric: Union[str, wandb_metric.Metric, None] = None,
        step_sync: bool = None,
        hidden: bool = None,
        summary: str = None,
        goal: str = None,
        overwrite: bool = None,
        **kwargs: Any,
    ) -> wandb_metric.Metric:
        """Define metric properties which will later be logged with `wandb.log()`.

        Arguments:
            name: Name of the metric.
            step_metric: Independent variable associated with the metric.
            step_sync: Automatically add `step_metric` to history if needed.
                Defaults to True if step_metric is specified.
            hidden: Hide this metric from automatic plots.
            summary: Specify aggregate metrics added to summary.
                Supported aggregations: "min,max,mean,best,last,none"
                Default aggregation is `copy`
                Aggregation `best` defaults to `goal`==`minimize`
            goal: Specify direction for optimizing the metric.
                Supported directions: "minimize,maximize"

        Returns:
            A metric object is returned that can be further specified.

        """
        return self._define_metric(
            name, step_metric, step_sync, hidden, summary, goal, overwrite, **kwargs
        )

    def _define_metric(
        self,
        name: str,
        step_metric: Union[str, wandb_metric.Metric, None] = None,
        step_sync: bool = None,
        hidden: bool = None,
        summary: str = None,
        goal: str = None,
        overwrite: bool = None,
        **kwargs: Any,
    ) -> wandb_metric.Metric:
        if not name:
            raise wandb.Error("define_metric() requires non-empty name argument")
        for k in kwargs:
            wandb.termwarn(f"Unhandled define_metric() arg: {k}")
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
                    "Unhandled define_metric() arg: {} type: {}".format(
                        arg_name, arg_type
                    )
                )
        stripped = name[:-1] if name.endswith("*") else name
        if "*" in stripped:
            raise wandb.Error(
                "Unhandled define_metric() arg: name (glob suffixes only): {}".format(
                    name
                )
            )
        summary_ops: Optional[Sequence[str]] = None
        if summary:
            summary_items = [s.lower() for s in summary.split(",")]
            summary_ops = []
            valid = {"min", "max", "mean", "best", "last", "copy", "none"}
            for i in summary_items:
                if i not in valid:
                    raise wandb.Error(f"Unhandled define_metric() arg: summary op: {i}")
                summary_ops.append(i)
        goal_cleaned: Optional[str] = None
        if goal is not None:
            goal_cleaned = goal[:3].lower()
            valid_goal = {"min", "max"}
            if goal_cleaned not in valid_goal:
                raise wandb.Error(f"Unhandled define_metric() arg: goal: {goal}")
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
        with telemetry.context(run=self) as tel:
            tel.feature.metric = True
        return m

    # TODO(jhr): annotate this
    @_run_decorator._attach
    def watch(self, models, criterion=None, log="gradients", log_freq=100, idx=None, log_graph=False) -> None:  # type: ignore
        wandb.watch(models, criterion, log, log_freq, idx, log_graph)

    # TODO(jhr): annotate this
    @_run_decorator._attach
    def unwatch(self, models=None) -> None:  # type: ignore
        wandb.unwatch(models=models)

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
            wandb.termwarn(
                f"Could not find {artifact_name} in launch artifact mapping. Searching for unique artifacts with sequence name: {artifact_name}"
            )
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
            wandb.termwarn(
                f"Could not find swappable artifact at key: {use_as}. Using {artifact_name}"
            )
            return artifact_name

        wandb.termwarn(
            f"Could not find {artifact_key_string} in launch artifact mapping. Using {artifact_name}"
        )
        return artifact_name

    def _detach(self) -> None:
        pass

    @_run_decorator._attach
    def link_artifact(
        self,
        artifact: Union[public.Artifact, Artifact],
        target_path: str,
        aliases: Optional[List[str]] = None,
    ) -> None:
        """Links the given artifact to a portfolio (a promoted collection of artifacts).

        The linked artifact will be visible in the UI for the specified portfolio.

        Arguments:
            artifact: the (public or local) artifact which will be linked
            target_path: `str` - takes the following forms: {portfolio}, {project}/{portfolio},
                or {entity}/{project}/{portfolio}
            aliases: `List[str]` - optional alias(es) that will only be applied on this linked artifact inside the portfolio.
            The alias "latest" will always be applied to the latest version of an artifact that is linked.

        Returns:
            None

        """
        portfolio, project, entity = wandb.util._parse_entity_project_item(target_path)
        if aliases is None:
            aliases = []

        if self._backend and self._backend.interface:
            if not self._settings._offline:
                self._backend.interface.publish_link_artifact(
                    self,
                    artifact,
                    portfolio,
                    aliases,
                    entity,
                    project,
                )
            else:
                # TODO: implement offline mode + sync
                raise NotImplementedError

    @_run_decorator._attach
    def use_artifact(
        self,
        artifact_or_name: Union[str, public.Artifact, Artifact],
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        use_as: Optional[str] = None,
    ) -> Union[public.Artifact, Artifact]:
        """Declare an artifact as an input to a run.

        Call `download` or `file` on the returned object to get the contents locally.

        Arguments:
            artifact_or_name: (str or Artifact) An artifact name.
                May be prefixed with entity/project/. Valid names
                can be in the following forms:
                    - name:version
                    - name:alias
                    - digest
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
                use_as=use_as or artifact_or_name,
            )
            return artifact
        else:
            artifact = artifact_or_name
            if aliases is None:
                aliases = []
            elif isinstance(aliases, str):
                aliases = [aliases]
            if isinstance(artifact_or_name, wandb.Artifact):
                if use_as is not None:
                    wandb.termwarn(
                        "Indicating use_as is not supported when using an artifact with an instance of `wandb.Artifact`"
                    )
                self._log_artifact(
                    artifact,
                    aliases=aliases,
                    is_user_created=True,
                    use_after_commit=True,
                )
                artifact.wait()
                artifact._use_as = use_as or artifact.name
                return artifact
            elif isinstance(artifact, public.Artifact):
                if (
                    self._launch_artifact_mapping
                    and artifact.name in self._launch_artifact_mapping.keys()
                ):
                    wandb.termwarn(
                        "Swapping artifacts is not supported when using an instance of `public.Artifact`. "
                        f"Using {artifact.name}."
                    )
                artifact._use_as = use_as or artifact.name
                api.use_artifact(
                    artifact.id, use_as=use_as or artifact._use_as or artifact.name
                )
                return artifact
            else:
                raise ValueError(
                    'You must pass an artifact name (e.g. "pedestrian-dataset:v1"), '
                    "an instance of `wandb.Artifact`, or `wandb.Api().artifact()` to `use_artifact`"  # noqa: E501
                )

    @_run_decorator._attach
    def log_artifact(
        self,
        artifact_or_path: Union[wandb_artifacts.Artifact, str],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
    ) -> wandb_artifacts.Artifact:
        """Declare an artifact as an output of a run.

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

        Returns:
            An `Artifact` object.
        """
        return self._log_artifact(
            artifact_or_path, name=name, type=type, aliases=aliases
        )

    @_run_decorator._attach
    def upsert_artifact(
        self,
        artifact_or_path: Union[wandb_artifacts.Artifact, str],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        distributed_id: Optional[str] = None,
    ) -> wandb_artifacts.Artifact:
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

    @_run_decorator._attach
    def finish_artifact(
        self,
        artifact_or_path: Union[wandb_artifacts.Artifact, str],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        distributed_id: Optional[str] = None,
    ) -> wandb_artifacts.Artifact:
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
        artifact_or_path: Union[wandb_artifacts.Artifact, str],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        distributed_id: Optional[str] = None,
        finalize: bool = True,
        is_user_created: bool = False,
        use_after_commit: bool = False,
    ) -> wandb_artifacts.Artifact:
        api = internal.Api()
        if api.settings().get("anonymous") == "true":
            wandb.termwarn(
                "Artifacts logged anonymously cannot be claimed and expire after 7 days."
            )
        if not finalize and distributed_id is None:
            raise TypeError("Must provide distributed_id if artifact is not finalize")
        if aliases is not None:
            if any(invalid in alias for alias in aliases for invalid in ["/", ":"]):
                raise ValueError(
                    "Aliases must not contain any of the following characters: /, :"
                )
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
                    self.step,
                    finalize=finalize,
                    is_user_created=is_user_created,
                    use_after_commit=use_after_commit,
                )
                artifact._logged_artifact = _LazyArtifact(self._public_api(), future)
            else:
                self._backend.interface.publish_artifact(
                    self,
                    artifact,
                    aliases,
                    finalize=finalize,
                    is_user_created=is_user_created,
                    use_after_commit=use_after_commit,
                )
        elif self._internal_run_interface:
            self._internal_run_interface.publish_artifact(
                self,
                artifact,
                aliases,
                finalize=finalize,
                is_user_created=is_user_created,
                use_after_commit=use_after_commit,
            )
        return artifact

    def _public_api(self, overrides: Optional[Dict[str, str]] = None) -> PublicApi:
        overrides = {"run": self._run_id}
        run_obj = self._run_obj
        if run_obj is not None:
            overrides["entity"] = run_obj.entity
            overrides["project"] = run_obj.project
        return public.Api(overrides)

    # TODO(jhr): annotate this
    def _assert_can_log_artifact(self, artifact) -> None:  # type: ignore
        if not self._settings._offline:
            try:
                public_api = self._public_api()
                expected_type = public.Artifact.expected_type(
                    public_api.client,
                    artifact.name,
                    public_api.settings["entity"],
                    public_api.settings["project"],
                )
            except requests.exceptions.RequestException:
                # Just return early if there is a network error. This is
                # ok, as this function is intended to help catch an invalid
                # type early, but not a hard requirement for valid operation.
                return
            if expected_type is not None and artifact.type != expected_type:
                raise ValueError(
                    "Expected artifact type {}, got {}".format(
                        expected_type, artifact.type
                    )
                )

    def _prepare_artifact(
        self,
        artifact_or_path: Union[wandb_artifacts.Artifact, str],
        name: Optional[str] = None,
        type: Optional[str] = None,
        aliases: Optional[List[str]] = None,
    ) -> Tuple[wandb_artifacts.Artifact, List[str]]:
        aliases = aliases or ["latest"]
        if isinstance(artifact_or_path, str):
            if name is None:
                name = f"run-{self._run_id}-{os.path.basename(artifact_or_path)}"
            artifact = wandb.Artifact(name, type)
            if os.path.isfile(artifact_or_path):
                artifact.add_file(artifact_or_path)
            elif os.path.isdir(artifact_or_path):
                artifact.add_dir(artifact_or_path)
            elif "://" in artifact_or_path:
                artifact.add_reference(artifact_or_path)
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
        if isinstance(aliases, str):
            aliases = [aliases]
        artifact.finalize()
        return artifact, aliases

    @_run_decorator._attach
    def alert(
        self,
        title: str,
        text: str,
        level: Union[str, "AlertLevel"] = None,
        wait_duration: Union[int, float, timedelta, None] = None,
    ) -> None:
        """Launch an alert with the given title and text.

        Arguments:
            title: (str) The title of the alert, must be less than 64 characters long.
            text: (str) The text body of the alert.
            level: (str or wandb.AlertLevel, optional) The alert level to use, either: `INFO`, `WARN`, or `ERROR`.
            wait_duration: (int, float, or timedelta, optional) The time to wait (in seconds) before sending another
                alert with this title.
        """
        level = level or wandb.AlertLevel.INFO
        level_str: str = level.value if isinstance(level, wandb.AlertLevel) else level
        if level_str not in {lev.value for lev in wandb.AlertLevel}:
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
        exit_code = 0 if exc_type is None else 1
        self._finish(exit_code)
        return exc_type is None

    @_run_decorator._attach
    def mark_preempting(self) -> None:
        """Marks this run as preempting.

        Also tells the internal process to immediately report this to server.
        """
        if self._backend and self._backend.interface:
            self._backend.interface.publish_preempting()

    # ------------------------------------------------------------------------------
    # HEADER
    # ------------------------------------------------------------------------------
    # Note: All the header methods are static methods since we want to share the printing logic
    # with the service execution path that doesn't have access to the run instance
    @staticmethod
    def _header(
        check_version: Optional["CheckVersionResponse"] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        # printer = printer or get_printer(settings._jupyter)
        Run._header_version_check_info(
            check_version, settings=settings, printer=printer
        )
        Run._header_wandb_version_info(settings=settings, printer=printer)
        Run._header_sync_info(settings=settings, printer=printer)
        Run._header_run_info(settings=settings, printer=printer)

    @staticmethod
    def _header_version_check_info(
        check_version: Optional["CheckVersionResponse"] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:

        if not check_version or settings._offline:
            return

        # printer = printer or get_printer(settings._jupyter)
        if check_version.delete_message:
            printer.display(check_version.delete_message, level="error")
        elif check_version.yank_message:
            printer.display(check_version.yank_message, level="warn")

        printer.display(
            check_version.upgrade_message, off=not check_version.upgrade_message
        )

    @staticmethod
    def _header_wandb_version_info(
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:
        if settings.quiet or settings.silent:
            return

        # printer = printer or get_printer(settings._jupyter)
        printer.display(f"Tracking run with wandb version {wandb.__version__}")

    @staticmethod
    def _header_sync_info(
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:

        # printer = printer or get_printer(settings._jupyter)
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

        run_state_str = "Resuming run" if settings.resumed else "Syncing run"
        run_name = settings.run_name

        # printer = printer or get_printer(settings._jupyter)
        if printer._html:
            if not wandb.jupyter.maybe_display():

                run_line = f"<strong>{printer.link(run_url, run_name)}</strong>"
                project_line, sweep_line = "", ""

                # TODO(settings): make settings the source of truth
                if not wandb.jupyter.quiet():

                    doc_html = printer.link(wburls.get("doc_run"), "docs")

                    project_html = printer.link(project_url, "Weights & Biases")
                    project_line = f"to {project_html} ({doc_html})"

                    if sweep_url:
                        sweep_line = (
                            f"Sweep page:  {printer.link(sweep_url, sweep_url)}"
                        )

                printer.display(
                    [f"{run_state_str} {run_line} {project_line}", sweep_line]
                )

        else:
            printer.display(f"{run_state_str} {printer.name(run_name)}")
            if not settings.quiet:
                printer.display(
                    f'{printer.emoji("star")} View project at {printer.link(project_url)}'
                )
                if sweep_url:
                    printer.display(
                        f'{printer.emoji("broom")} View sweep at {printer.link(sweep_url)}'
                    )
            printer.display(
                f'{printer.emoji("rocket")} View run at {printer.link(run_url)}'
            )

            # TODO(settings) use `wandb_settings` (if self.settings.anonymous == "true":)
            if Api().api.settings().get("anonymous") == "true":
                printer.display(
                    "Do NOT share these links with anyone. They can be used to claim your runs.",
                    level="warn",
                )

    # ------------------------------------------------------------------------------
    # FOOTER
    # ------------------------------------------------------------------------------
    # Note: All the footer methods are static methods since we want to share the printing logic
    # with the service execution path that doesn't have acess to the run instance
    @staticmethod
    def _footer(
        sampled_history: Optional["SampledHistoryResponse"] = None,
        final_summary: Optional["GetSummaryResponse"] = None,
        poll_exit_response: Optional[PollExitResponse] = None,
        check_version: Optional["CheckVersionResponse"] = None,
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
            pool_exit_response=poll_exit_response,
            quiet=quiet,
            settings=settings,
            printer=printer,
        )
        Run._footer_log_dir_info(quiet=quiet, settings=settings, printer=printer)
        Run._footer_version_check_info(
            check_version=check_version, quiet=quiet, settings=settings, printer=printer
        )
        Run._footer_local_warn(
            poll_exit_response=poll_exit_response,
            quiet=quiet,
            settings=settings,
            printer=printer,
        )
        Run._footer_reporter_warn_err(
            reporter=reporter, quiet=quiet, settings=settings, printer=printer
        )
        Run._footer_server_messages(
            poll_exit_response=poll_exit_response,
            quiet=quiet,
            settings=settings,
            printer=printer,
        )

    @staticmethod
    def _footer_exit_status_info(
        exit_code: Optional[int],
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:

        if settings.silent:
            return

        status = "(success)." if not exit_code else f"(failed {exit_code})."
        info = [
            f"Waiting for W&B process to finish... {printer.status(status, bool(exit_code))}"
        ]

        if not settings._offline and exit_code:
            info.append(f"Press {printer.abort()} to abort syncing.")

        printer.display(f'{" ".join(info)}')

    # fixme: Temporary hack until we move to rich which allows multiple spinners
    @staticmethod
    def _footer_file_pusher_status_info(
        poll_exit_responses: Optional[
            Union[PollExitResponse, Dict[str, Optional[PollExitResponse]]]
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
        elif isinstance(poll_exit_responses, dict):
            poll_exit_responses_list = [
                response for response in poll_exit_responses.values()
            ]
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
            raise ValueError(
                f"Got the type `{type(poll_exit_responses)}` for `poll_exit_responses`. "
                "Expected either None, PollExitResponse or a Dict[str, Union[PollExitResponse, None]]"
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

        progress = poll_exit_response.pusher_stats
        done = poll_exit_response.done

        megabyte = wandb.util.POW_2_BYTES[2][1]
        line = (
            f"{progress.uploaded_bytes / megabyte :.3f} MB of {progress.total_bytes / megabyte:.3f} MB uploaded "
            f"({progress.deduped_bytes / megabyte:.3f} MB deduped)\r"
        )

        percent_done = (
            1.0
            if progress.total_bytes == 0
            else progress.uploaded_bytes / progress.total_bytes
        )

        printer.progress_update(line, percent_done)
        if done:
            printer.progress_close()

            dedupe_fraction = (
                progress.deduped_bytes / float(progress.total_bytes)
                if progress.total_bytes > 0
                else 0
            )
            if dedupe_fraction > 0.01:
                printer.display(
                    f"W&B sync reduced upload amount by {dedupe_fraction * 100:.1f}%             "
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
        total_files = sum(
            sum(
                [
                    response.file_counts.wandb_count,
                    response.file_counts.media_count,
                    response.file_counts.artifact_count,
                    response.file_counts.other_count,
                ]
            )
            for response in poll_exit_responses
            if response and response.file_counts
        )
        uploaded = sum(
            response.pusher_stats.uploaded_bytes
            for response in poll_exit_responses
            if response and response.pusher_stats
        )
        total = sum(
            response.pusher_stats.total_bytes
            for response in poll_exit_responses
            if response and response.pusher_stats
        )

        line = f"Processing {len(poll_exit_responses)} runs with {total_files} files ({uploaded/megabyte :.2f} MB/{total/megabyte :.2f} MB)\r"
        # line = "{}{:<{max_len}}\r".format(line, " ", max_len=(80 - len(line)))
        printer.progress_update(line)  # type: ignore [call-arg]

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
        pool_exit_response: Optional[PollExitResponse] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:

        if settings.silent:
            return

        # printer = printer or get_printer(settings._jupyter)

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
                info = [
                    f"Synced {printer.name(settings.run_name)}: {printer.link(settings.run_url)}"
                ]
            if pool_exit_response and pool_exit_response.file_counts:

                logger.info("logging synced files")
                file_counts = pool_exit_response.file_counts
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

        # printer = printer or get_printer(settings._jupyter)
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
            final_summary = {
                item.key: json.loads(item.value_json)
                for item in summary.item
                if not item.key.startswith("_")
            }

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
    def _footer_local_warn(
        poll_exit_response: Optional[PollExitResponse] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:

        if (quiet or settings.quiet) or settings.silent:
            return

        if settings._offline:
            return

        if not poll_exit_response or not poll_exit_response.local_info:
            return

        if settings.is_local:
            local_info = poll_exit_response.local_info
            latest_version, out_of_date = local_info.version, local_info.out_of_date
            if out_of_date:
                # printer = printer or get_printer(settings._jupyter)
                printer.display(
                    f"Upgrade to the {latest_version} version of W&B Server to get the latest features. "
                    f"Learn more: {printer.link(wburls.get('upgrade_server'))}",
                    level="warn",
                )

    @staticmethod
    def _footer_server_messages(
        poll_exit_response: Optional[PollExitResponse] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:

        if (quiet or settings.quiet) or settings.silent:
            return

        if settings.disable_hints:
            return

        if poll_exit_response and poll_exit_response.server_messages:
            for message in poll_exit_response.server_messages.item:
                printer.display(
                    message.html_text if printer._html else message.utf_text,
                    default_text=message.plain_text,
                    level=message.level,
                    off=message.type.lower() != "footer",
                )

    @staticmethod
    def _footer_version_check_info(
        check_version: Optional["CheckVersionResponse"] = None,
        quiet: Optional[bool] = None,
        *,
        settings: "Settings",
        printer: Union["PrinterTerm", "PrinterJupyter"],
    ) -> None:

        if not check_version:
            return

        if settings._offline:
            return

        if (quiet or settings.quiet) or settings.silent:
            return

        # printer = printer or get_printer(settings._jupyter)
        if check_version.delete_message:
            printer.display(check_version.delete_message, level="error")
        elif check_version.yank_message:
            printer.display(check_version.yank_message, level="warn")

        # only display upgrade message if packages are bad
        package_problem = check_version.delete_message or check_version.yank_message
        if package_problem and check_version.upgrade_message:
            printer.display(check_version.upgrade_message)

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

        # printer = printer or get_printer(settings._jupyter)

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
    """Downloads the specified file from cloud storage.

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


def finish(exit_code: int = None, quiet: bool = None) -> None:
    """Marks a run as finished, and finishes uploading all data.

    This is used when creating multiple runs in the same process.
    We automatically call this method when your script exits.

    Arguments:
        exit_code: Set to something other than 0 to mark a run as failed
        quiet: Set to true to minimize log output
    """
    if wandb.run:
        wandb.run.finish(exit_code=exit_code, quiet=quiet)


class _LazyArtifact(ArtifactInterface):

    _api: PublicApi
    _instance: Optional[ArtifactInterface] = None
    _future: Any

    def __init__(self, api: PublicApi, future: Any):
        self._api = api
        self._future = future

    def _assert_instance(self) -> ArtifactInterface:
        if not self._instance:
            raise ValueError(
                "Must call wait() before accessing logged artifact properties"
            )
        return self._instance

    def __getattr__(self, item: str) -> Any:
        self._assert_instance()
        return getattr(self._instance, item)

    def wait(self) -> ArtifactInterface:
        if not self._instance:
            resp = self._future.get().response.log_artifact_response
            if resp.error_message:
                raise ValueError(resp.error_message)
            self._instance = public.Artifact.from_id(resp.artifact_id, self._api.client)
        assert isinstance(
            self._instance, ArtifactInterface
        ), "Insufficient permissions to fetch Artifact with id {} from {}".format(
            resp.artifact_id, self._api.client.app_url
        )
        return self._instance

    @property
    def id(self) -> Optional[str]:
        return self._assert_instance().id

    @property
    def version(self) -> str:
        return self._assert_instance().version

    @property
    def name(self) -> str:
        return self._assert_instance().name

    @property
    def type(self) -> str:
        return self._assert_instance().type

    @property
    def entity(self) -> str:
        return self._assert_instance().entity

    @property
    def project(self) -> str:
        return self._assert_instance().project

    @property
    def manifest(self) -> "ArtifactManifest":
        return self._assert_instance().manifest

    @property
    def digest(self) -> str:
        return self._assert_instance().digest

    @property
    def state(self) -> str:
        return self._assert_instance().state

    @property
    def size(self) -> int:
        return self._assert_instance().size

    @property
    def commit_hash(self) -> str:
        return self._assert_instance().commit_hash

    @property
    def description(self) -> Optional[str]:
        return self._assert_instance().description

    @description.setter
    def description(self, desc: Optional[str]) -> None:
        self._assert_instance().description = desc

    @property
    def metadata(self) -> dict:
        return self._assert_instance().metadata

    @metadata.setter
    def metadata(self, metadata: dict) -> None:
        self._assert_instance().metadata = metadata

    @property
    def aliases(self) -> List[str]:
        return self._assert_instance().aliases

    @aliases.setter
    def aliases(self, aliases: List[str]) -> None:
        self._assert_instance().aliases = aliases

    def used_by(self) -> List["wandb.apis.public.Run"]:
        return self._assert_instance().used_by()

    def logged_by(self) -> "wandb.apis.public.Run":
        return self._assert_instance().logged_by()

    # Commenting this block out since this code is unreachable since LocalArtifact
    # overrides them and therefore untestable.
    # Leaving behind as we may want to support these in the future.

    # def new_file(self, name: str, mode: str = "w") -> Any:  # TODO: Refine Type
    #     return self._assert_instance().new_file(name, mode)

    # def add_file(
    #     self,
    #     local_path: str,
    #     name: Optional[str] = None,
    #     is_tmp: Optional[bool] = False,
    # ) -> Any:  # TODO: Refine Type
    #     return self._assert_instance().add_file(local_path, name, is_tmp)

    # def add_dir(self, local_path: str, name: Optional[str] = None) -> None:
    #     return self._assert_instance().add_dir(local_path, name)

    # def add_reference(
    #     self,
    #     uri: Union["ArtifactEntry", str],
    #     name: Optional[str] = None,
    #     checksum: bool = True,
    #     max_objects: Optional[int] = None,
    # ) -> Any:  # TODO: Refine Type
    #     return self._assert_instance().add_reference(uri, name, checksum, max_objects)

    # def add(self, obj: "WBValue", name: str) -> Any:  # TODO: Refine Type
    #     return self._assert_instance().add(obj, name)

    def get_path(self, name: str) -> "ArtifactEntry":
        return self._assert_instance().get_path(name)

    def get(self, name: str) -> "WBValue":
        return self._assert_instance().get(name)

    def download(self, root: Optional[str] = None, recursive: bool = False) -> str:
        return self._assert_instance().download(root, recursive)

    def checkout(self, root: Optional[str] = None) -> str:
        return self._assert_instance().checkout(root)

    def verify(self, root: Optional[str] = None) -> Any:
        return self._assert_instance().verify(root)

    def save(self) -> None:
        return self._assert_instance().save()

    def delete(self) -> None:
        return self._assert_instance().delete()
