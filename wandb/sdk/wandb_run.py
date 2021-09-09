#
# -*- coding: utf-8 -*-

from __future__ import print_function

import atexit
from datetime import timedelta
import glob
import json
import logging
import numbers
import os
import platform
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
    Optional,
    Sequence,
    TextIO,
    Tuple,
    Type,
    Union,
)
from typing import TYPE_CHECKING

import click
import requests
from six import iteritems, string_types
from six.moves import _thread as thread
from six.moves.collections_abc import Mapping
from six.moves.urllib.parse import quote as url_quote
from six.moves.urllib.parse import urlencode
import wandb
from wandb import errors
from wandb import trigger
from wandb._globals import _datatypes_set_callback
from wandb.apis import internal, public
from wandb.apis.public import Api as PublicApi
from wandb.errors import Error
from wandb.proto.wandb_internal_pb2 import (
    FilePusherStats,
    MetricRecord,
    PollExitResponse,
    RunRecord,
)
from wandb.util import (
    add_import_hook,
    is_unicode_safe,
    sentry_set_scope,
    to_forward_slash_path,
)
from wandb.viz import (
    create_custom_chart,
    custom_chart_panel_config,
    CustomChart,
    Visualize,
)

from . import wandb_artifacts
from . import wandb_config
from . import wandb_history
from . import wandb_metric
from . import wandb_summary
from .interface.artifacts import Artifact as ArtifactInterface
from .interface.interface import BackendSender
from .interface.summary_record import SummaryRecord
from .lib import (
    apikey,
    config_util,
    filenames,
    filesystem,
    ipython,
    module,
    proto_util,
    redirect,
    sparkline,
    telemetry,
)
from .lib.reporting import Reporter
from .wandb_artifacts import Artifact
from .wandb_settings import Settings, SettingsConsole
from .wandb_setup import _WandbSetup


if TYPE_CHECKING:
    from typing import NoReturn

    from .data_types import WBValue

    from .interface.artifacts import (
        ArtifactEntry,
        ArtifactManifest,
    )


logger = logging.getLogger("wandb")
EXIT_TIMEOUT = 60
RUN_NAME_COLOR = "#cdcd00"
RE_LABEL = re.compile(r"[a-zA-Z0-9_-]+$")


class ExitHooks(object):

    exception: Optional[BaseException] = None

    def __init__(self) -> None:
        self.exit_code = 0
        self.exception = None

    def hook(self) -> None:
        self._orig_exit = sys.exit
        sys.exit = self.exit
        self._orig_excepthook = (
            sys.excepthook
            if sys.excepthook
            != sys.__excepthook__  # respect hooks by other libraries like pdb
            else None
        )
        sys.excepthook = self.exc_handler

    def exit(self, code: object = 0) -> "NoReturn":
        orig_code = code
        if code is None:
            code = 0
        elif not isinstance(code, int):
            code = 1
        self.exit_code = code
        self._orig_exit(orig_code)

    def was_ctrl_c(self) -> bool:
        return isinstance(self.exception, KeyboardInterrupt)

    def exc_handler(
        self, exc_type: Type[BaseException], exc: BaseException, tb: TracebackType
    ) -> None:
        self.exit_code = 1
        self.exception = exc
        if issubclass(exc_type, Error):
            wandb.termerror(str(exc))

        if self.was_ctrl_c():
            self.exit_code = 255

        traceback.print_exception(exc_type, exc, tb)
        if self._orig_excepthook:
            self._orig_excepthook(exc_type, exc, tb)


class RunStatusChecker(object):
    """Periodically polls the background process for relevant updates.

    For now, we just use this to figure out if the user has requested a stop.
    """

    def __init__(
        self,
        interface: BackendSender,
        stop_polling_interval: int = 15,
        retry_polling_interval: int = 5,
    ) -> None:
        self._interface = interface
        self._stop_polling_interval = stop_polling_interval
        self._retry_polling_interval = retry_polling_interval

        self._join_event = threading.Event()
        self._stop_thread = threading.Thread(target=self.check_status)
        self._stop_thread.daemon = True
        self._stop_thread.start()

        self._retry_thread = threading.Thread(target=self.check_network_status)
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
                        wandb.termlog("{}".format(hr.http_response_text))
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


class Run(object):
    """A unit of computation logged by wandb. Typically this is an ML experiment.

    Create a run with `wandb.init()`.

    In distributed training, use `wandb.init()` to create a run for
    each process, and set the group argument to organize runs into a larger experiment.

    Currently there is a parallel Run object in the wandb.Api. Eventually these
    two objects will be merged.

    Attributes:
        history: (History) Time series values, created with `wandb.log()`.
            History can contain scalar values, rich media, or even custom plots
            across multiple steps.
        summary: (Summary) Single values set for each `wandb.log()` key. By
            default, summary is set to the last value logged. You can manually
            set summary to the best value, like max accuracy, instead of the
            final value.
    """

    _telemetry_obj: telemetry.TelemetryRecord
    _teardown_hooks: List[Callable[[], None]]
    _tags: Optional[Tuple[Any, ...]]

    _entity: Optional[str]
    _project: Optional[str]
    _group: Optional[str]
    _job_type: Optional[str]
    _name: Optional[str]
    _notes: Optional[str]

    _run_obj: Optional[RunRecord]
    _run_obj_offline: Optional[RunRecord]
    # Use string literal anotation because of type reference loop
    _backend: Optional["wandb.sdk.backend.backend.Backend"]
    _wl: Optional[_WandbSetup]

    _upgraded_version_message: Optional[str]
    _deleted_version_message: Optional[str]
    _yanked_version_message: Optional[str]

    _out_redir: Optional[redirect.RedirectBase]
    _err_redir: Optional[redirect.RedirectBase]
    _redirect_cb: Optional[Callable[[str, str], None]]
    _output_writer: Optional["filesystem.CRDedupedFile"]

    _atexit_cleanup_called: bool
    _hooks: Optional[ExitHooks]
    _exit_code: Optional[int]

    _run_status_checker: Optional[RunStatusChecker]
    _poll_exit_response: Optional[PollExitResponse]

    _sampled_history: Optional[Dict[str, Union[List[int], List[float]]]]

    _use_redirect: bool
    _stdout_slave_fd: Optional[int]
    _stderr_slave_fd: Optional[int]

    _pid: int

    def __init__(
        self,
        settings: Settings,
        config: Optional[Dict[str, Any]] = None,
        sweep_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._config = wandb_config.Config()
        self._config._set_callback(self._config_callback)
        self._config._set_settings(settings)
        self._backend = None
        self.summary = wandb_summary.Summary(
            self._summary_get_current_summary_callback,
        )
        self.summary._set_update_callback(self._summary_update_callback)
        self.history = wandb_history.History(self)
        self.history._set_callback(self._history_callback)

        _datatypes_set_callback(self._datatypes_callback)

        self._settings = settings
        self._wl = None
        self._reporter: Optional[Reporter] = None

        self._entity = None
        self._project = None
        self._group = None
        self._job_type = None
        self._run_id = settings.run_id
        self._start_time = time.time()
        self._starting_step = 0
        self._name = None
        self._notes = None
        self._tags = None

        self._hooks = None
        self._teardown_hooks = []
        self._redirect_cb = None
        self._out_redir = None
        self._err_redir = None
        self.stdout_redirector = None
        self.stderr_redirector = None
        self._save_stdout = None
        self._save_stderr = None
        self._stdout_slave_fd = None
        self._stderr_slave_fd = None
        self._exit_code = None
        self._exit_result = None
        self._final_summary = None
        self._sampled_history = None
        self._jupyter_progress = None
        if self._settings._jupyter and ipython._get_python_type() == "jupyter":
            self._jupyter_progress = ipython.jupyter_progress_bar()

        self._output_writer = None
        self._upgraded_version_message = None
        self._deleted_version_message = None
        self._yanked_version_message = None

        # Pull info from settings
        self._init_from_settings(settings)

        # Initial scope setup for sentry. This might get changed when the
        # actual run comes back.
        sentry_set_scope(
            "user",
            entity=self._entity,
            project=self._project,
            email=self._settings.email,
        )

        # Returned from backend request_run(), set from wandb_init?
        self._run_obj = None
        self._run_obj_offline = None

        # Created when the run "starts".
        self._run_status_checker = None

        self._poll_exit_response = None

        # Initialize telemetry object
        self._telemetry_obj = telemetry.TelemetryRecord()

        # Populate config
        config = config or dict()
        wandb_key = "_wandb"
        config.setdefault(wandb_key, dict())
        if settings.save_code and settings.program_relpath:
            config[wandb_key]["code_path"] = to_forward_slash_path(
                os.path.join("code", settings.program_relpath)
            )
        if sweep_config:
            self._config.update_locked(
                sweep_config, user="sweep", _allow_val_change=True
            )

        if (
            self._settings.launch
            and self._settings.launch_config_path
            and os.path.exists(self._settings.launch_config_path)
        ):
            with open(self._settings.launch_config_path) as fp:
                launch_config = json.loads(fp.read())
            self._config.update_locked(
                launch_config, user="launch", _allow_val_change=True
            )
        self._config._update(config, ignore_locked=True)

        self._atexit_cleanup_called = False
        self._use_redirect = True
        self._progress_step = 0

        self._pid = os.getpid()

    def _telemetry_callback(self, telem_obj: telemetry.TelemetryRecord) -> None:
        self._telemetry_obj.MergeFrom(telem_obj)

    def _freeze(self) -> None:
        self._frozen = True

    def __setattr__(self, attr: str, value: object) -> None:
        if getattr(self, "_frozen", None) and not hasattr(self, attr):
            raise Exception("Attribute {} is not supported on Run object.".format(attr))
        super(Run, self).__setattr__(attr, value)

    def _telemetry_imports(self, imp: telemetry.TelemetryImports) -> None:
        mods = sys.modules
        if mods.get("torch"):
            imp.torch = True
        if mods.get("keras"):
            imp.keras = True
        if mods.get("tensorflow"):
            imp.tensorflow = True
        if mods.get("sklearn"):
            imp.sklearn = True
        if mods.get("fastai"):
            imp.fastai = True
        if mods.get("xgboost"):
            imp.xgboost = True
        if mods.get("catboost"):
            imp.catboost = True
        if mods.get("lightgbm"):
            imp.lightgbm = True
        if mods.get("pytorch_lightning"):
            imp.pytorch_lightning = True
        if mods.get("ignite"):
            imp.pytorch_ignite = True
        if mods.get("transformers"):
            imp.transformers_huggingface = True
        if mods.get("jax"):
            imp.jax = True
        if mods.get("metaflow"):
            imp.metaflow = True

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
            run.start_time.FromSeconds(int(self._start_time))
        # Note: run.config is set in interface/interface:_make_run()

    def __getstate__(self) -> None:
        pass

    def __setstate__(self, state: Any) -> None:
        pass

    @property
    def dir(self) -> str:
        """Returns the directory where files associated with the run are saved."""
        return self._settings.files_dir

    @property
    def config(self) -> wandb_config.Config:
        """Returns the config object associated with this run."""
        return self._config

    @property
    def config_static(self) -> wandb_config.ConfigStatic:
        return wandb_config.ConfigStatic(self._config)

    @property
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
        if self._backend:
            self._backend.interface.publish_run(self)

    @property
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
        if self._backend:
            self._backend.interface.publish_run(self)

    @property
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
        if self._backend:
            self._backend.interface.publish_run(self)

    @property
    def id(self) -> str:
        """Returns the identifier for this run."""
        if TYPE_CHECKING:
            assert self._run_id is not None
        return self._run_id

    @property
    def sweep_id(self) -> Optional[str]:
        """Returns the ID of the sweep associated with the run, if there is one."""
        if not self._run_obj:
            return None
        return self._run_obj.sweep_id or None

    @property
    def path(self) -> str:
        """Returns the path to the run.

        Run paths include entity, project, and run ID, in the format
        `entity/project/run_id`.
        """
        parts = []
        for e in [self._entity, self._project, self._run_id]:
            if e is not None:
                parts.append(e)
        return "/".join(parts)

    @property
    def start_time(self) -> float:
        """Returns the unix time stamp, in seconds, when the run started."""
        if not self._run_obj:
            return self._start_time
        else:
            return self._run_obj.start_time.ToSeconds()

    @property
    def starting_step(self) -> int:
        """Returns the first step of the run."""
        if not self._run_obj:
            return self._starting_step
        else:
            return self._run_obj.starting_step

    @property
    def resumed(self) -> bool:
        """Returns True if the run was resumed, False otherwise."""
        if self._run_obj:
            return self._run_obj.resumed
        return False

    @property
    def step(self) -> int:
        """Returns the current value of the step.

        This counter is incremented by `wandb.log`."""
        return self.history._step

    def project_name(self) -> str:
        run_obj = self._run_obj or self._run_obj_offline
        return run_obj.project if run_obj else ""

    @property
    def mode(self) -> str:
        """For compatibility with `0.9.x` and earlier, deprecate eventually."""
        return "dryrun" if self._settings._offline else "run"

    @property
    def offline(self) -> bool:
        return self._settings._offline

    @property
    def disabled(self) -> bool:
        return self._settings._noop

    @property
    def group(self) -> str:
        """Returns the name of the group associated with the run.

        Setting a group helps the W&B UI organize runs in a sensible way.

        If you are doing a distributed training you should give all of the
            runs in the training the same group.
        If you are doing crossvalidation you should give all the crossvalidation
            folds the same group.
        """
        run_obj = self._run_obj or self._run_obj_offline
        return run_obj.run_group if run_obj else ""

    @property
    def job_type(self) -> str:
        run_obj = self._run_obj or self._run_obj_offline
        return run_obj.job_type if run_obj else ""

    @property
    def project(self) -> str:
        """Returns the name of the W&B project associated with the run."""
        return self.project_name()

    def log_code(
        self,
        root: str = ".",
        name: str = None,
        include_fn: Callable[[str], bool] = lambda path: path.endswith(".py"),
        exclude_fn: Callable[[str], bool] = filenames.exclude_wandb_fn,
    ) -> Optional[Artifact]:
        """Saves the current state of your code to a W&B artifact.

        By default it walks the current directory and logs all files that end with `.py`.

        Arguments:
            root (str, optional): The relative (to `os.getcwd()`) or absolute path to
                recursively find code from.
            name (str, optional): The name of our code artifact. By default we'll name
                the artifact `source-$RUN_ID`. There may be scenarios where you want
                many runs to share the same artifact. Specifying name allows you to achieve that.
            include_fn (callable, optional): A callable that accepts a file path and
                returns True when it should be included and False otherwise. This
                defaults to: `lambda path: path.endswith(".py")`
            exclude_fn (callable, optional): A callable that accepts a file path and
                returns `True` when it should be excluded and `False` otherwise. This
                defaults to: `lambda path: False`

        Examples:
            Basic usage
            ```python
            run.log_code()
            ```

            Advanced usage
            ```python
            run.log_code("../", include_fn=lambda path: path.endswith(".py") or path.endswith(".ipynb"))
            ```

        Returns:
            An `Artifact` object if code was logged
        """
        name = name or "{}-{}".format("source", self.id)
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
        return self.log_artifact(art)

    def get_url(self) -> Optional[str]:
        """Returns the url for the W&B run, if there is one.

        Offline runs will not have a url.
        """
        if not self._run_obj:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._get_run_url()

    def get_project_url(self) -> Optional[str]:
        """Returns the url for the W&B project associated with the run, if there is one.

        Offline runs will not have a project url.
        """
        if not self._run_obj:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._get_project_url()

    def get_sweep_url(self) -> Optional[str]:
        """Returns the url for the sweep associated with the run, if there is one."""
        if not self._run_obj:
            wandb.termwarn("URL not available in offline run")
            return None
        return self._get_sweep_url()

    @property
    def url(self) -> Optional[str]:
        """Returns the W&B url associated with the run."""
        return self.get_url()

    @property
    def entity(self) -> str:
        """Returns the name of the W&B entity associated with the run.

        Entity can be a user name or the name of a team or organization."""
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
                "Label added for unsupported key '{}' (ignored).".format(v),
                repeat=False,
            )

        self._label_internal(code=code, repo=repo, code_version=code_version)

        # update telemetry in the backend immediately for _label() callers
        if self._backend:
            self._backend.interface.publish_telemetry(self._telemetry_obj)

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
        except Exception as e:
            logger.info("Unable to probe notebook: {}".format(e))
            return
        if lines:
            self._label_probe_lines(lines)

    def _repr_mimebundle_(
        self, include: Any = None, exclude: Any = None
    ) -> Dict[str, str]:
        url = self._get_run_url()
        style = "border:none;width:100%;height:400px"
        s = '<h1>Run({})</h1><iframe src="{}" style="{}"></iframe>'.format(
            self._run_id, url, style
        )
        return {"text/html": s}

    def _config_callback(
        self,
        key: Union[Tuple[str, ...], str] = None,
        val: Any = None,
        data: Dict[str, object] = None,
    ) -> None:
        logger.info("config_cb %s %s %s", key, val, data)
        if not self._backend or not self._backend.interface:
            return
        self._backend.interface.publish_config(key=key, val=val, data=data)

    def _set_config_wandb(self, key: str, val: Any) -> None:
        self._config_callback(key=("_wandb", key), val=val)

    def _summary_update_callback(self, summary_record: SummaryRecord) -> None:
        if self._backend:
            self._backend.interface.publish_summary(summary_record)

    def _summary_get_current_summary_callback(self) -> Dict[str, Any]:
        if not self._backend:
            return {}
        ret = self._backend.interface.communicate_summary()
        return proto_util.dict_from_proto_list(ret.item)

    def _metric_callback(self, metric_record: MetricRecord) -> None:
        if self._backend:
            self._backend.interface._publish_metric(metric_record)

    def _datatypes_callback(self, fname: str) -> None:
        if not self._backend:
            return
        files = dict(files=[(fname, "now")])
        self._backend.interface.publish_files(files)

    # TODO(jhr): codemod add: PEP 3102 -- Keyword-Only Arguments
    def _history_callback(self, row: Dict[str, Any], step: int) -> None:

        # TODO(jhr): move visualize hack somewhere else
        custom_charts = {}
        for k in row:
            if isinstance(row[k], Visualize):
                config = {
                    "id": row[k].viz_id,
                    "historyFieldSettings": {"key": k, "x-axis": "_step"},
                }
                row[k] = row[k].value
                self._config_callback(val=config, key=("_wandb", "viz", k))
            elif isinstance(row[k], CustomChart):
                custom_charts[k] = row[k]
                custom_chart = row[k]

        for k, custom_chart in custom_charts.items():
            # remove the chart key from the row
            # TODO: is this really the right move? what if the user logs
            #     a non-custom chart to this key?
            row.pop(k)
            # add the table under a different key
            table_key = k + "_table"
            row[table_key] = custom_chart.table
            # add the panel
            panel_config = custom_chart_panel_config(custom_chart, k, table_key)
            self._add_panel(k, "Vega2", panel_config)

        if self._backend:
            not_using_tensorboard = len(wandb.patched["tensorboard"]) == 0
            self._backend.interface.publish_history(
                row, step, publish_step=not_using_tensorboard
            )

    def _console_callback(self, name: str, data: str) -> None:
        # logger.info("console callback: %s, %s", name, data)
        if self._backend:
            self._backend.interface.publish_output(name, data)

    def _tensorboard_callback(
        self, logdir: str, save: bool = None, root_logdir: str = None
    ) -> None:
        logger.info("tensorboard callback: %s, %s", logdir, save)
        save = True if save is None else save
        if self._backend:
            self._backend.interface.publish_tbdata(logdir, save, root_logdir)

    def _set_library(self, library: _WandbSetup) -> None:
        self._wl = library

    def _set_backend(self, backend: "wandb.sdk.backend.backend.Backend") -> None:
        self._backend = backend

    def _set_reporter(self, reporter: Reporter) -> None:
        self._reporter = reporter

    def _set_teardown_hooks(self, hooks: List[Callable[[], None]]) -> None:
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
            self.config._update(c_dict, allow_val_change=True, ignore_locked=True)
        # Update the summary, this will trigger an un-needed graphql request :(
        if run_obj.summary:
            summary_dict = {}
            for orig in run_obj.summary.update:
                summary_dict[orig.key] = json.loads(orig.value_json)
            self.summary.update(summary_dict)
        self.history._update_step()
        # TODO: It feels weird to call this twice..
        sentry_set_scope(
            "user",
            entity=run_obj.entity,
            project=run_obj.project,
            email=self._settings.email,
            url=self._get_run_url(),
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

        if data_type not in self.config["_wandb"]:
            self.config["_wandb"][data_type] = {}

        if data_type in self.config["_wandb"][data_type]:
            old_value = self.config["_wandb"][data_type][key]
        else:
            old_value = None

        if value_extra != old_value:
            self.config["_wandb"][data_type][key] = value_extra
            self.config.persist()

    def log(
        self,
        data: Dict[str, Any],
        step: int = None,
        commit: bool = None,
        sync: bool = None,
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
        calling `wandb.log({"train-loss": 0.5, commit=False})` and then
        `wandb.log({"accuracy": 0.9})` is equivalent to calling
        `wandb.log({"train-loss": 0.5, "accuracy": 0.9})`.

        `wandb.log` is not intended to be called more than a few times per second.
        If you want to log more frequently than that it's better to aggregate
        the data on the client side or you may get degraded performance.

        Arguments:
            row: (dict, optional) A dict of serializable python objects i.e `str`,
                `ints`, `floats`, `Tensors`, `dicts`, or any of the `wandb.data_types`.
            commit: (boolean, optional) Save the metrics dict to the wandb server
                and increment the step.  If false `wandb.log` just updates the current
                metrics dict with the row argument and metrics won't be saved until
                `wandb.log` is called with `commit=True`.
            step: (integer, optional) The global step in processing. This persists
                any non-committed earlier steps but defaults to not committing the
                specified step.
            sync: (boolean, True) This argument is deprecated and currently doesn't
                change the behaviour of `wandb.log`.

        Examples:
            For more and more detailed examples, see
            [our guides to logging](https://docs.wandb.com/guides/track/log).

            Basic usage
            ```python
            wandb.log({'accuracy': 0.9, 'epoch': 5})
            ```

            Incremental logging
            ```python
            wandb.log({'loss': 0.2}, commit=False)
            # Somewhere else when I'm ready to report this step:
            wandb.log({'accuracy': 0.8})
            ```

            Histogram
            ```python
            wandb.log({"gradients": wandb.Histogram(numpy_array_or_sequence)})
            ```

            Image
            ```python
            wandb.log({"examples": [wandb.Image(numpy_array_or_pil, caption="Label")]})
            ```

            Video
            ```python
            wandb.log({"video": wandb.Video(numpy_array_or_video_path, fps=4,
                format="gif")})
            ```

            Matplotlib Plot
            ```python
            wandb.log({"chart": plt})
            ```

            PR Curve
            ```python
            wandb.log({'pr': wandb.plots.precision_recall(y_test, y_probas, labels)})
            ```

            3D Object
            ```python
            wandb.log({"generated_samples":
            [wandb.Object3D(open("sample.obj")),
                wandb.Object3D(open("sample.gltf")),
                wandb.Object3D(open("sample.glb"))]})
            ```

        Raises:
            wandb.Error: if called before `wandb.init`
            ValueError: if invalid data is passed

        """
        current_pid = os.getpid()
        if current_pid != self._pid:
            message = "log() ignored (called from pid={}, init called from pid={}). See: https://docs.wandb.ai/library/init#multiprocess".format(
                current_pid, self._pid
            )
            if self._settings._strict:
                wandb.termerror(message, repeat=False)
                raise errors.LogMultiprocessError(
                    "log() does not support multiprocessing"
                )
            wandb.termwarn(message, repeat=False)
            return

        if not isinstance(data, Mapping):
            raise ValueError("wandb.log must be passed a dictionary")

        if any(not isinstance(key, string_types) for key in data.keys()):
            raise ValueError("Key values passed to `wandb.log` must be strings.")

        if step is not None:
            # if step is passed in when tensorboard_sync is used we honor the step passed
            # to make decisions about how to close out the history record, but will strip
            # this history later on in publish_history()
            using_tensorboard = len(wandb.patched["tensorboard"]) > 0
            if using_tensorboard:
                wandb.termwarn(
                    "Step cannot be set when using syncing with tensorboard. Please log your step values as a metric such as 'global_step'",
                    repeat=False,
                )
            if self.history._step > step:
                wandb.termwarn(
                    (
                        "Step must only increase in log calls.  "
                        "Step {} < {}; dropping {}.".format(
                            step, self.history._step, data
                        )
                    )
                )
                return
            elif step > self.history._step:
                self.history._flush()
                self.history._step = step
        elif commit is None:
            commit = True
        if commit:
            self.history._row_add(data)
        else:
            self.history._row_update(data)

    def save(
        self,
        glob_str: Optional[str] = None,
        base_path: Optional[str] = None,
        policy: str = "live",
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
            wandb.termwarn(
                (
                    "Calling run.save without any arguments is deprecated."
                    "Changes to attributes are automatically persisted."
                )
            )
            return True
        if policy not in ("live", "end", "now"):
            raise ValueError(
                'Only "live" "end" and "now" policies are currently supported.'
            )
        if isinstance(glob_str, bytes):
            glob_str = glob_str.decode("utf-8")
        if not isinstance(glob_str, string_types):
            raise ValueError("Must call wandb.save(glob_str) with glob_str a str")

        if base_path is None:
            if os.path.isabs(glob_str):
                base_path = os.path.dirname(glob_str)
                wandb.termwarn(
                    (
                        "Saving files without folders. If you want to preserve "
                        "sub directories pass base_path to wandb.save, i.e. "
                        'wandb.save("/mnt/folder/file.h5", base_path="/mnt")'
                    )
                )
            else:
                base_path = "."
        wandb_glob_str = os.path.relpath(glob_str, base_path)
        if ".." + os.sep in wandb_glob_str:
            raise ValueError("globs can't walk above base_path")

        with telemetry.context(run=self) as tel:
            tel.feature.save = True

        if glob_str.startswith("gs://") or glob_str.startswith("s3://"):
            wandb.termlog(
                "%s is a cloud storage url, can't save file to wandb." % glob_str
            )
            return []
        files = glob.glob(os.path.join(self.dir, wandb_glob_str))
        warn = False
        if len(files) == 0 and "*" in wandb_glob_str:
            warn = True
        for path in glob.glob(glob_str):
            file_name = os.path.relpath(path, base_path)
            abs_path = os.path.abspath(path)
            wandb_path = os.path.join(self.dir, file_name)
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
        files_dict = dict(files=[(wandb_glob_str, policy)])
        if self._backend:
            self._backend.interface.publish_files(files_dict)
        return files

    def restore(
        self,
        name: str,
        run_path: Optional[str] = None,
        replace: bool = False,
        root: Optional[str] = None,
    ) -> Union[None, TextIO]:
        return restore(name, run_path or self.path, replace, root or self.dir)

    def finish(self, exit_code: int = None) -> None:
        """Marks a run as finished, and finishes uploading all data.

        This is used when creating multiple runs in the same process. We automatically
        call this method when your script exits or if you use the run context manager.
        """
        with telemetry.context(run=self) as tel:
            tel.feature.finish = True
        # detach logger, other setup cleanup
        logger.info("finishing run %s", self.path)
        for hook in self._teardown_hooks:
            hook()
        self._teardown_hooks = []
        self._atexit_cleanup(exit_code=exit_code)
        if self._wl and len(self._wl._global_run_stack) > 0:
            self._wl._global_run_stack.pop()
        module.unset_globals()

    def join(self, exit_code: int = None) -> None:
        """Deprecated alias for `finish()` - please use finish."""
        self.finish(exit_code=exit_code)

    # TODO(jhr): annotate this
    def plot_table(self, vega_spec_name, data_table, fields, string_fields=None):  # type: ignore
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
        visualization = create_custom_chart(
            vega_spec_name, data_table, fields, string_fields or {}
        )
        return visualization

    def _set_upgraded_version_message(self, msg: str) -> None:
        self._upgraded_version_message = msg

    def _set_deleted_version_message(self, msg: str) -> None:
        self._deleted_version_message = msg

    def _set_yanked_version_message(self, msg: str) -> None:
        self._yanked_version_message = msg

    def _add_panel(
        self, visualize_key: str, panel_type: str, panel_config: dict
    ) -> None:
        config = {
            "panel_type": panel_type,
            "panel_config": panel_config,
        }
        self._config_callback(val=config, key=("_wandb", "visualize", visualize_key))

    def _get_url_query_string(self) -> str:
        s = self._settings

        # TODO(jhr): migrate to new settings, but for now this is safer
        api = internal.Api()
        if api.settings().get("anonymous") != "true":
            return ""

        api_key = apikey.api_key(settings=s)
        return "?" + urlencode({"apiKey": api_key})

    def _get_project_url(self) -> str:
        s = self._settings
        r = self._run_obj
        if not r:
            return ""
        app_url = wandb.util.app_url(s.base_url)
        qs = self._get_url_query_string()
        url = "{}/{}/{}{}".format(
            app_url, url_quote(r.entity), url_quote(r.project), qs
        )
        return url

    def _get_run_url(self) -> str:
        s = self._settings
        r = self._run_obj
        if not r:
            return ""
        app_url = wandb.util.app_url(s.base_url)
        qs = self._get_url_query_string()
        url = "{}/{}/{}/runs/{}{}".format(
            app_url, url_quote(r.entity), url_quote(r.project), url_quote(r.run_id), qs
        )
        return url

    def _get_sweep_url(self) -> str:
        """Generate a url for a sweep.

        Returns:
            (str): url if the run is part of a sweep
            (None): if the run is not part of the sweep
        """
        r = self._run_obj
        if not r:
            return ""
        sweep_id = r.sweep_id
        if not sweep_id:
            return ""

        app_url = wandb.util.app_url(self._settings.base_url)
        qs = self._get_url_query_string()

        return "{base}/{entity}/{project}/sweeps/{sweepid}{qs}".format(
            base=app_url,
            entity=url_quote(r.entity),
            project=url_quote(r.project),
            sweepid=url_quote(sweep_id),
            qs=qs,
        )

    def _get_run_name(self) -> str:
        r = self._run_obj
        if not r:
            return ""
        return r.display_name

    def _display_run(self) -> None:
        project_url = self._get_project_url()
        run_url = self._get_run_url()
        sweep_url = self._get_sweep_url()
        version_str = "Tracking run with wandb version {}".format(wandb.__version__)
        if self.resumed:
            run_state_str = "Resuming run"
        else:
            run_state_str = "Syncing run"
        run_name = self._get_run_name()
        app_url = wandb.util.app_url(self._settings.base_url)

        sync_dir = self._settings._sync_dir
        if self._settings._jupyter:
            sync_dir = "<code>{}</code>".format(sync_dir)
        dir_str = "Run data is saved locally in {}".format(sync_dir)
        if self._settings._jupyter and ipython._get_python_type() == "jupyter":
            sweep_line = (
                'Sweep page: <a href="{}" target="_blank">{}</a><br/>\n'.format(
                    sweep_url, sweep_url
                )
                if sweep_url
                else ""
            )
            docs_html = '<a href="https://docs.wandb.com/integrations/jupyter.html" target="_blank">(Documentation)</a>'  # noqa: E501
            ipython.display_html(
                """
                {}<br/>
                {} <strong style="color:{}">{}</strong> to <a href="{}" target="_blank">Weights & Biases</a> {}.<br/>
                Project page: <a href="{}" target="_blank">{}</a><br/>
                {}Run page: <a href="{}" target="_blank">{}</a><br/>
                {}<br/><br/>
            """.format(  # noqa: E501
                    version_str,
                    run_state_str,
                    RUN_NAME_COLOR,
                    run_name,
                    app_url,
                    docs_html,
                    project_url,
                    project_url,
                    sweep_line,
                    run_url,
                    run_url,
                    dir_str,
                )
            )
        else:
            wandb.termlog(version_str)
            wandb.termlog(
                "{} {}".format(run_state_str, click.style(run_name, fg="yellow"))
            )
            emojis = dict(star="", broom="", rocket="")
            if platform.system() != "Windows" and is_unicode_safe(sys.stdout):
                emojis = dict(star="⭐️", broom="🧹", rocket="🚀")

            wandb.termlog(
                "{} View project at {}".format(
                    emojis.get("star", ""),
                    click.style(project_url, underline=True, fg="blue"),
                )
            )
            if sweep_url:
                wandb.termlog(
                    "{} View sweep at {}".format(
                        emojis.get("broom", ""),
                        click.style(sweep_url, underline=True, fg="blue"),
                    )
                )
            wandb.termlog(
                "{} View run at {}".format(
                    emojis.get("rocket", ""),
                    click.style(run_url, underline=True, fg="blue"),
                )
            )
            wandb.termlog(dir_str)
            if not self._settings._offline:
                wandb.termlog("Run `wandb offline` to turn off syncing.")
            print("")

    def _redirect(
        self,
        stdout_slave_fd: Optional[int],
        stderr_slave_fd: Optional[int],
        console: SettingsConsole = None,
    ) -> None:
        if console is None:
            console = self._settings._console
        logger.info("redirect: %s", console)

        out_redir: redirect.RedirectBase
        err_redir: redirect.RedirectBase
        if console == self._settings.Console.REDIRECT:
            logger.info("Redirecting console.")
            out_redir = redirect.Redirect(
                src="stdout",
                cbs=[
                    lambda data: self._redirect_cb("stdout", data),  # type: ignore
                    self._output_writer.write,  # type: ignore
                ],
            )
            err_redir = redirect.Redirect(
                src="stderr",
                cbs=[
                    lambda data: self._redirect_cb("stderr", data),  # type: ignore
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
                    self._redirect(None, None, console=self._settings.Console.WRAP)

                add_import_hook("tensorflow", wrap_fallback)
        elif console == self._settings.Console.WRAP:
            logger.info("Wrapping output streams.")
            out_redir = redirect.StreamWrapper(
                src="stdout",
                cbs=[
                    lambda data: self._redirect_cb("stdout", data),  # type: ignore
                    self._output_writer.write,  # type: ignore
                ],
            )
            err_redir = redirect.StreamWrapper(
                src="stderr",
                cbs=[
                    lambda data: self._redirect_cb("stderr", data),  # type: ignore
                    self._output_writer.write,  # type: ignore
                ],
            )
        elif console == self._settings.Console.OFF:
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
        if self._use_redirect:
            if self._out_redir:
                self._out_redir.uninstall()
            if self._err_redir:
                self._err_redir.uninstall()
            return

        if self.stdout_redirector:
            self.stdout_redirector.restore()
        if self.stderr_redirector:
            self.stderr_redirector.restore()
        if self._save_stdout:
            sys.stdout = self._save_stdout
        if self._save_stderr:
            sys.stderr = self._save_stderr
        logger.info("restore done")

    def _atexit_cleanup(self, exit_code: int = None) -> None:
        if self._backend is None:
            logger.warning("process exited without backend configured")
            return
        if self._atexit_cleanup_called:
            return
        self._atexit_cleanup_called = True

        exit_code = exit_code or self._hooks.exit_code if self._hooks else 0
        logger.info("got exitcode: %d", exit_code)
        if exit_code == 0:
            # Cleanup our resume file on a clean exit
            if os.path.exists(self._settings.resume_fname):
                os.remove(self._settings.resume_fname)

        self._exit_code = exit_code
        try:
            self._on_finish()
        except KeyboardInterrupt as ki:
            if wandb.wandb_agent._is_running():
                raise ki
            wandb.termerror("Control-C detected -- Run data was not synced")
            if ipython._get_python_type() == "python":
                os._exit(-1)
        except Exception as e:
            self._console_stop()
            self._backend.cleanup()
            logger.error("Problem finishing run", exc_info=e)
            wandb.termerror("Problem finishing run")
            traceback.print_exception(*sys.exc_info())
            if ipython._get_python_type() == "python":
                os._exit(-1)
        else:
            # if silent, skip this as it is used to output stuff
            if self._settings._silent:
                return
            self._on_final()

    def _console_start(self) -> None:
        logger.info("atexit reg")
        self._hooks = ExitHooks()
        self._hooks.hook()
        atexit.register(lambda: self._atexit_cleanup())

        if self._use_redirect:
            # setup fake callback
            self._redirect_cb = self._console_callback

        output_log_path = os.path.join(self.dir, filenames.OUTPUT_FNAME)
        self._output_writer = filesystem.CRDedupedFile(open(output_log_path, "wb"))
        self._redirect(self._stdout_slave_fd, self._stderr_slave_fd)

    def _console_stop(self) -> None:
        self._restore()
        if self._output_writer:
            self._output_writer.close()
            self._output_writer = None

    def _on_init(self) -> None:
        self._show_version_info()

    def _on_start(self) -> None:
        # TODO: make offline mode in jupyter use HTML
        if self._settings._offline:
            wandb.termlog(
                (
                    "W&B syncing is set to `offline` in this directory.  "
                    "Run `wandb online` or set WANDB_MODE=online to enable cloud syncing."
                )
            )
        if self._settings.save_code and self._settings.code_dir is not None:
            self.log_code(self._settings.code_dir)
        if self._run_obj and not self._settings._silent:
            self._display_run()
        if self._backend and not self._settings._offline:
            self._run_status_checker = RunStatusChecker(self._backend.interface)
        self._console_start()

    def _pusher_print_status(
        self,
        progress: FilePusherStats,
        prefix: bool = True,
        done: Optional[bool] = False,
    ) -> None:
        if self._settings._offline:
            return

        line = " %.2fMB of %.2fMB uploaded (%.2fMB deduped)\r" % (
            progress.uploaded_bytes / 1048576.0,
            progress.total_bytes / 1048576.0,
            progress.deduped_bytes / 1048576.0,
        )

        if self._jupyter_progress:
            percent_done: float
            if progress.total_bytes == 0:
                percent_done = 1
            else:
                percent_done = progress.uploaded_bytes / progress.total_bytes
            self._jupyter_progress.update(percent_done, line)
            if done:
                self._jupyter_progress.close()
        elif not self._settings._jupyter:
            spinner_states = ["-", "\\", "|", "/"]

            line = spinner_states[self._progress_step % 4] + line
            self._progress_step += 1
            wandb.termlog(line, newline=False, prefix=prefix)

            if done:
                dedupe_fraction = (
                    progress.deduped_bytes / float(progress.total_bytes)
                    if progress.total_bytes > 0
                    else 0
                )
                if dedupe_fraction > 0.01:
                    wandb.termlog(
                        "W&B sync reduced upload amount by %.1f%%             "
                        % (dedupe_fraction * 100),
                        prefix=prefix,
                    )
                # clear progress line.
                wandb.termlog(" " * 79, prefix=prefix)

    def _on_finish_progress(self, progress: FilePusherStats, done: bool = None) -> None:
        self._pusher_print_status(progress, done=done)

    def _wait_for_finish(self) -> PollExitResponse:
        while True:
            if self._backend:
                poll_exit_resp = self._backend.interface.communicate_poll_exit()
            logger.info("got exit ret: %s", poll_exit_resp)

            if poll_exit_resp:
                done = poll_exit_resp.done
                pusher_stats = poll_exit_resp.pusher_stats
                if pusher_stats:
                    self._on_finish_progress(pusher_stats, done)
                if done:
                    return poll_exit_resp
            time.sleep(0.1)

    def _on_finish(self) -> None:
        trigger.call("on_finished")

        # populate final import telemetry
        with telemetry.context(run=self) as tel:
            self._telemetry_imports(tel.imports_finish)

        if self._run_status_checker:
            self._run_status_checker.stop()

        # make sure all uncommitted history is flushed
        self.history._flush()

        self._console_stop()  # TODO: there's a race here with jupyter console logging
        if not self._settings._silent:
            if self._backend:
                pid = self._backend._internal_pid
                status_str = "Waiting for W&B process to finish, PID {}".format(pid)
            if not self._exit_code:
                status_str += "\nProgram ended successfully."
            else:
                status_str += "\nProgram failed with code {}. ".format(self._exit_code)
                if not self._settings._offline:
                    status_str += " Press ctrl-c to abort syncing."
            if self._settings._jupyter and ipython._get_python_type() == "jupyter":
                ipython.display_html("<br/>" + status_str.replace("\n", "<br/>"))
            else:
                print("")
                wandb.termlog(status_str)

        # telemetry could have changed, publish final data
        if self._backend:
            self._backend.interface.publish_telemetry(self._telemetry_obj)

        # TODO: we need to handle catastrophic failure better
        # some tests were timing out on sending exit for reasons not clear to me
        if self._backend:
            self._backend.interface.publish_exit(self._exit_code)

        # Wait for data to be synced
        self._poll_exit_response = self._wait_for_finish()

        if self._backend:
            ret = self._backend.interface.communicate_summary()
            self._final_summary = proto_util.dict_from_proto_list(ret.item)

        if self._backend:
            ret = self._backend.interface.communicate_sampled_history()
            d = {item.key: item.values_float or item.values_int for item in ret.item}
            self._sampled_history = d

        if self._backend:
            self._backend.cleanup()

        if self._run_status_checker:
            self._run_status_checker.join()

    def _on_final(self) -> None:
        # check for warnings and errors, show log file locations
        if self._reporter:
            # TODO: handle warnings and errors nicely in jupyter
            warning_lines = self._reporter.warning_lines
            if warning_lines:
                wandb.termlog("Warnings:")
                for line in warning_lines:
                    wandb.termlog(line)
                if len(warning_lines) < self._reporter.warning_count:
                    wandb.termlog("More warnings")

            error_lines = self._reporter.error_lines
            if error_lines:
                wandb.termlog("Errors:")
                for line in error_lines:
                    wandb.termlog(line)
                if len(error_lines) < self._reporter.error_count:
                    wandb.termlog("More errors")
        if self._settings.log_user:
            log_user = self._settings.log_user
            if self._settings._jupyter:
                log_user = "<code>{}</code>".format(log_user)
            log_str = "Find user logs for this run at: {}".format(log_user)
            if self._settings._jupyter and ipython._get_python_type() == "jupyter":
                ipython.display_html(log_str)
            else:
                wandb.termlog(log_str)
        if self._settings.log_internal:
            log_internal = self._settings.log_internal
            if self._settings._jupyter:
                log_internal = "<code>{}</code>".format(log_internal)
            log_str = "Find internal logs for this run at: {}".format(log_internal)
            if self._settings._jupyter and ipython._get_python_type() == "jupyter":
                ipython.display_html(log_str)
            else:
                wandb.termlog(log_str)

        self._show_summary()
        self._show_history()
        self._show_files()

        if self._run_obj:
            run_url = self._get_run_url()
            run_name = self._get_run_name()
            if self._settings._jupyter and ipython._get_python_type() == "jupyter":
                ipython.display_html(
                    """
                    <br/>Synced <strong style="color:{}">{}</strong>: <a href="{}" target="_blank">{}</a><br/>
                """.format(
                        RUN_NAME_COLOR, run_name, run_url, run_url
                    )
                )
            else:
                wandb.termlog(
                    "\nSynced {}: {}".format(
                        click.style(run_name, fg="yellow"),
                        click.style(run_url, fg="blue"),
                    )
                )

        if self._settings._offline:
            # TODO: handle jupyter offline messages
            wandb.termlog("You can sync this run to the cloud by running:")
            wandb.termlog(
                click.style(
                    "wandb sync {}".format(self._settings._sync_dir), fg="yellow"
                )
            )

        self._show_version_info(footer=True)
        self._show_local_warning()

    def _show_version_info(self, footer: bool = None) -> None:
        package_problem = False
        if self._deleted_version_message:
            wandb.termerror(self._deleted_version_message)
            package_problem = True
        elif self._yanked_version_message:
            wandb.termwarn(self._yanked_version_message)
            package_problem = True
        # only display upgrade message if packages are bad or in header
        if not footer or package_problem:
            if self._upgraded_version_message:
                wandb.termlog(self._upgraded_version_message)

    def _show_summary(self) -> None:
        if self._final_summary:
            logger.info("rendering summary")
            max_len = 0
            summary_rows = []
            for k, v in sorted(iteritems(self._final_summary)):
                # arrays etc. might be too large. for now we just don't print them
                if k.startswith("_"):
                    continue
                if isinstance(v, string_types):
                    if len(v) >= 20:
                        v = v[:20] + "..."
                    summary_rows.append((k, v))
                elif isinstance(v, numbers.Number):
                    if isinstance(v, float):
                        v = round(v, 5)
                    summary_rows.append((k, v))
                else:
                    continue
                max_len = max(max_len, len(k))
            if not summary_rows:
                return
            if self._settings._jupyter and ipython._get_python_type() == "jupyter":
                summary_table = ipython.STYLED_TABLE_HTML
                for row in summary_rows:
                    summary_table += "<tr><td>{}</td><td>{}</td></tr>".format(*row)
                summary_table += "</table>"
                ipython.display_html("<h3>Run summary:</h3><br/>" + summary_table)
            else:
                format_str = "  {:>%s} {}" % max_len
                summary_lines = "\n".join(
                    [format_str.format(k, v) for k, v in summary_rows]
                )
                wandb.termlog("Run summary:")
                wandb.termlog(summary_lines)

    def _show_history(self) -> None:
        if not self._sampled_history:
            return

        # Only print sparklines if the terminal is utf-8
        # In some python 2.7 tests sys.stdout is a 'cStringIO.StringO' object
        #   which doesn't have the attribute 'encoding'
        encoding = getattr(sys.stdout, "encoding", None)
        if not encoding or encoding.upper() not in ("UTF_8", "UTF-8",):
            return

        logger.info("rendering history")
        max_len = 0
        history_rows = []
        for key in sorted(self._sampled_history):
            if key.startswith("_"):
                continue
            vals = wandb.util.downsample(self._sampled_history[key], 40)
            if any((not isinstance(v, numbers.Number) for v in vals)):
                continue
            line = sparkline.sparkify(vals)
            history_rows.append((key, line))
            max_len = max(max_len, len(key))
        if not history_rows:
            return
        if self._settings._jupyter and ipython._get_python_type() == "jupyter":
            history_table = ipython.STYLED_TABLE_HTML
            for row in history_rows:
                history_table += "<tr><td>{}</td><td>{}</td></tr>".format(*row)
            history_table += "</table>"
            ipython.display_html("<h3>Run history:</h3><br/>" + history_table + "<br/>")
        else:
            wandb.termlog("Run history:")
            history_lines = ""
            format_str = "  {:>%s} {}\n" % max_len
            for row in history_rows:
                history_lines += format_str.format(*row)
            wandb.termlog(history_lines.rstrip())

    def _show_local_warning(self) -> None:
        if not self._poll_exit_response or not self._poll_exit_response.local_info:
            return

        if self._settings._offline:
            return

        if self._settings.is_local:
            local_info = self._poll_exit_response.local_info
            latest_version, out_of_date = local_info.version, local_info.out_of_date
            if out_of_date:
                wandb.termwarn(
                    f"Upgrade to the {latest_version} version of W&B Local to get the latest features. Learn more: http://wandb.me/local-upgrade"
                )

    def _show_files(self) -> None:
        if not self._poll_exit_response or not self._poll_exit_response.file_counts:
            return
        if self._settings._offline:
            return

        logger.info("logging synced files")

        if self._settings._silent:
            return

        file_str = "Synced {} W&B file(s), {} media file(s), {} artifact file(s) and {} other file(s)".format(  # noqa:E501
            self._poll_exit_response.file_counts.wandb_count,
            self._poll_exit_response.file_counts.media_count,
            self._poll_exit_response.file_counts.artifact_count,
            self._poll_exit_response.file_counts.other_count,
        )
        if self._settings._jupyter and ipython._get_python_type() == "jupyter":
            ipython.display_html(file_str)
        else:
            wandb.termlog(file_str)

    def _save_job_spec(self) -> None:
        envdict = dict(python="python3.6", requirements=[],)
        varsdict = {"WANDB_DISABLE_CODE": "True"}
        source = dict(
            git="git@github.com:wandb/examples.git", branch="master", commit="bbd8d23",
        )
        execdict = dict(
            program="train.py",
            directory="keras-cnn-fashion",
            envvars=varsdict,
            args=[],
        )
        configdict = (dict(self._config),)
        artifactsdict = dict(dataset="v1",)
        inputdict = dict(config=configdict, artifacts=artifactsdict,)
        job_spec = {
            "kind": "WandbJob",
            "version": "v0",
            "environment": envdict,
            "source": source,
            "exec": execdict,
            "input": inputdict,
        }

        s = json.dumps(job_spec, indent=4)
        spec_filename = filenames.JOBSPEC_FNAME
        with open(spec_filename, "w") as f:
            print(s, file=f)
        self.save(spec_filename)

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
                Supported direections: "minimize,maximize"

        Returns:
            A metric object is returned that can be further specified.

        """
        if not name:
            raise wandb.Error("define_metric() requires non-empty name argument")
        for k in kwargs:
            wandb.termwarn("Unhandled define_metric() arg: {}".format(k))
        if isinstance(step_metric, wandb_metric.Metric):
            step_metric = step_metric.name
        for arg_name, arg_val, exp_type in (
            ("name", name, string_types),
            ("step_metric", step_metric, string_types),
            ("step_sync", step_sync, bool),
            ("hidden", hidden, bool),
            ("summary", summary, string_types),
            ("goal", goal, string_types),
            ("overwrite", overwrite, bool),
        ):
            # NOTE: type checking is broken for isinstance and string_types
            if arg_val is not None and not isinstance(arg_val, exp_type):  # type: ignore
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
                    raise wandb.Error(
                        "Unhandled define_metric() arg: summary op: {}".format(i)
                    )
                summary_ops.append(i)
        goal_cleaned: Optional[str] = None
        if goal is not None:
            goal_cleaned = goal[:3].lower()
            valid_goal = {"min", "max"}
            if goal_cleaned not in valid_goal:
                raise wandb.Error(
                    "Unhandled define_metric() arg: goal: {}".format(goal)
                )
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
    def watch(self, models, criterion=None, log="gradients", log_freq=100, idx=None, log_graph=False) -> None:  # type: ignore
        wandb.watch(models, criterion, log, log_freq, idx, log_graph)

    # TODO(jhr): annotate this
    def use_artifact(self, artifact_or_name, type=None, aliases=None):  # type: ignore
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
        Returns:
            An `Artifact` object.
        """
        if self.offline:
            raise TypeError("Cannot use artifact when in offline mode.")

        r = self._run_obj
        api = internal.Api(default_settings={"entity": r.entity, "project": r.project})
        api.set_current_run_id(self.id)

        if isinstance(artifact_or_name, str):
            name = artifact_or_name
            public_api = self._public_api()
            artifact = public_api.artifact(type=type, name=name)
            if type is not None and type != artifact.type:
                raise ValueError(
                    "Supplied type {} does not match type {} of artifact {}".format(
                        type, artifact.type, artifact.name
                    )
                )
            api.use_artifact(artifact.id)
            return artifact
        else:
            artifact = artifact_or_name
            if aliases is None:
                aliases = []
            elif isinstance(aliases, str):
                aliases = [aliases]
            if isinstance(artifact_or_name, wandb.Artifact):
                self._log_artifact(
                    artifact, aliases, is_user_created=True, use_after_commit=True
                )
                return artifact
            elif isinstance(artifact, public.Artifact):
                api.use_artifact(artifact.id)
                return artifact
            else:
                raise ValueError(
                    'You must pass an artifact name (e.g. "pedestrian-dataset:v1"), an instance of wandb.Artifact, or wandb.Api().artifact() to use_artifact'  # noqa: E501
                )

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
        return self._log_artifact(artifact_or_path, name, type, aliases)

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
        if self.group == "" and distributed_id is None:
            raise TypeError(
                "Cannot upsert artifact unless run is in a group or distributed_id is provided"
            )
        if distributed_id is None:
            distributed_id = self.group
        return self._log_artifact(
            artifact_or_path,
            name,
            type,
            aliases,
            distributed_id=distributed_id,
            finalize=False,
        )

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
        if self.group == "" and distributed_id is None:
            raise TypeError(
                "Cannot finish artifact unless run is in a group or distributed_id is provided"
            )
        if distributed_id is None:
            distributed_id = self.group

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
        if self._backend:
            if not self._settings._offline:
                future = self._backend.interface.communicate_artifact(
                    self,
                    artifact,
                    aliases,
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
        return artifact

    def _public_api(self) -> PublicApi:
        overrides = {"run": self.id}
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
                name = "run-%s-%s" % (self.id, os.path.basename(artifact_or_path))
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

    def alert(
        self,
        title: str,
        text: str,
        level: Union[str, None] = None,
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
        if isinstance(level, wandb.AlertLevel):
            level = level.value
        if level not in (
            wandb.AlertLevel.INFO.value,
            wandb.AlertLevel.WARN.value,
            wandb.AlertLevel.ERROR.value,
        ):
            raise ValueError("level must be one of 'INFO', 'WARN', or 'ERROR'")

        wait_duration = wait_duration or timedelta(minutes=1)
        if isinstance(wait_duration, int) or isinstance(wait_duration, float):
            wait_duration = timedelta(seconds=wait_duration)
        elif not callable(getattr(wait_duration, "total_seconds", None)):
            raise ValueError(
                "wait_duration must be an int, float, or datetime.timedelta"
            )
        wait_duration = int(wait_duration.total_seconds() * 1000)

        if self._backend:
            self._backend.interface.publish_alert(title, text, level, wait_duration)

    def __enter__(self) -> "Run":
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException],
        exc_val: BaseException,
        exc_tb: TracebackType,
    ) -> bool:
        exit_code = 0 if exc_type is None else 1
        self.finish(exit_code)
        return exc_type is None

    def mark_preempting(self) -> None:
        """Marks this run as preempting.

        Also tells the internal process to immediately report this to server.
        """
        if self._backend:
            self._backend.interface.publish_preempting()


# We define this outside of the run context to support restoring before init
def restore(
    name: str,
    run_path: Optional[str] = None,
    replace: bool = False,
    root: Optional[str] = None,
) -> Union[None, TextIO]:
    """Downloads the specified file from cloud storage.

    File is placed into the current directory or run directory.
    By default will only download the file if it doesn't already exist.

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
        return open(path, "r")
    if is_disabled:
        return None
    files = api_run.files([name])
    if len(files) == 0:
        return None
    # if the file does not exist, the file has an md5 of 0
    if files[0].md5 == "0":
        raise ValueError("File {} not found in {}.".format(name, run_path or root))
    return files[0].download(root=root, replace=True)


# propigate our doc string to the runs restore method
try:
    Run.restore.__doc__ = restore.__doc__
# py2 doesn't let us set a doc string, just pass
except AttributeError:
    pass


def finish(exit_code: int = None) -> None:
    """Marks a run as finished, and finishes uploading all data.

    This is used when creating multiple runs in the same process.
    We automatically call this method when your script exits.
    """
    if wandb.run:
        wandb.run.finish(exit_code=exit_code)


# propagate our doc string to the runs restore method
try:
    Run.restore.__doc__ = restore.__doc__
# py2 doesn't let us set a doc string, just pass
except AttributeError:
    pass


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
