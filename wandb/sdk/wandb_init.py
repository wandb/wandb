"""Defines wandb.init() and associated classes and methods.

`wandb.init()` indicates the beginning of a new run. In an ML training pipeline,
you could add `wandb.init()` to the beginning of your training script as well as
your evaluation script, and each step would be tracked as a run in W&B.

For more on using `wandb.init()`, including code snippets, check out our
[guide and FAQs](https://docs.wandb.ai/guides/track/launch).
"""

import copy
import json
import logging
import os
import platform
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union

import wandb
import wandb.env
from wandb import trigger
from wandb.errors import CommError, Error, UsageError
from wandb.errors.util import ProtobufErrorHandler
from wandb.integration import sagemaker
from wandb.integration.magic import magic_install
from wandb.sdk.lib import runid
from wandb.sdk.lib.paths import StrPath
from wandb.util import _is_artifact_representation

from . import wandb_login, wandb_setup
from .backend.backend import Backend
from .lib import SummaryDisabled, filesystem, ipython, module, reporting, telemetry
from .lib.deprecate import Deprecated, deprecate
from .lib.mailbox import Mailbox, MailboxProgress
from .lib.printer import Printer, get_printer
from .lib.wburls import wburls
from .wandb_helper import parse_config
from .wandb_run import Run, TeardownHook, TeardownStage
from .wandb_settings import Settings, Source

if TYPE_CHECKING:
    from wandb.proto import wandb_internal_pb2 as pb

logger: Optional[logging.Logger] = None  # logger configured during wandb.init()


def _set_logger(log_object: logging.Logger) -> None:
    """Configure module logger."""
    global logger
    logger = log_object


def _huggingface_version() -> Optional[str]:
    if "transformers" in sys.modules:
        trans = wandb.util.get_module("transformers")
        if hasattr(trans, "__version__"):
            return str(trans.__version__)
    return None


def _maybe_mp_process(backend: Backend) -> bool:
    parent_process = getattr(
        backend._multiprocessing, "parent_process", None
    )  # New in version 3.8.
    if parent_process:
        return parent_process() is not None
    process = backend._multiprocessing.current_process()
    if process.name == "MainProcess":
        return False
    if process.name.startswith("Process-"):
        return True
    return False


def _handle_launch_config(settings: "Settings") -> Dict[str, Any]:
    launch_run_config: Dict[str, Any] = {}
    if not settings.launch:
        return launch_run_config
    if os.environ.get("WANDB_CONFIG") is not None:
        try:
            launch_run_config = json.loads(os.environ.get("WANDB_CONFIG", "{}"))
        except (ValueError, SyntaxError):
            wandb.termwarn("Malformed WANDB_CONFIG, using original config")
    elif settings.launch_config_path and os.path.exists(settings.launch_config_path):
        with open(settings.launch_config_path) as fp:
            launch_config = json.loads(fp.read())
        launch_run_config = launch_config.get("overrides", {}).get("run_config")
    else:
        i = 0
        chunks = []
        while True:
            key = f"WANDB_CONFIG_{i}"
            if key in os.environ:
                chunks.append(os.environ[key])
                i += 1
            else:
                break
        if len(chunks) > 0:
            config_string = "".join(chunks)
            try:
                launch_run_config = json.loads(config_string)
            except (ValueError, SyntaxError):
                wandb.termwarn("Malformed WANDB_CONFIG, using original config")

    return launch_run_config


class _WandbInit:
    _init_telemetry_obj: telemetry.TelemetryRecord

    def __init__(self) -> None:
        self.kwargs = None
        self.settings: Optional[Settings] = None
        self.sweep_config: Dict[str, Any] = {}
        self.launch_config: Dict[str, Any] = {}
        self.config: Dict[str, Any] = {}
        self.run: Optional[Run] = None
        self.backend: Optional[Backend] = None

        self._teardown_hooks: List[TeardownHook] = []
        self._wl: Optional[wandb_setup._WandbSetup] = None
        self._reporter: Optional[wandb.sdk.lib.reporting.Reporter] = None
        self.notebook: Optional[wandb.jupyter.Notebook] = None  # type: ignore
        self.printer: Optional[Printer] = None

        self._init_telemetry_obj = telemetry.TelemetryRecord()

        self.deprecated_features_used: Dict[str, str] = dict()

    def _setup_printer(self, settings: Settings) -> None:
        if self.printer:
            return
        self.printer = get_printer(settings._jupyter)

    def setup(self, kwargs: Any) -> None:  # noqa: C901
        """Complete setup for `wandb.init()`.

        This includes parsing all arguments, applying them with settings and enabling logging.
        """
        self.kwargs = kwargs

        # if the user ran, for example, `wandb.login(`) before `wandb.init()`,
        # the singleton will already be set up and so if e.g. env vars are set
        # in between, they will be ignored, which we need to inform the user about.
        singleton = wandb_setup._WandbSetup._instance
        if singleton is not None:
            self._setup_printer(settings=singleton._settings)
            assert self.printer
            exclude_env_vars = {"WANDB_SERVICE", "WANDB_KUBEFLOW_URL"}
            # check if environment variables have changed
            singleton_env = {
                k: v
                for k, v in singleton._environ.items()
                if k.startswith("WANDB_") and k not in exclude_env_vars
            }
            os_env = {
                k: v
                for k, v in os.environ.items()
                if k.startswith("WANDB_") and k not in exclude_env_vars
            }
            if set(singleton_env.keys()) != set(os_env.keys()) or set(
                singleton_env.values()
            ) != set(os_env.values()):
                line = (
                    "Changes to your `wandb` environment variables will be ignored "
                    "because your `wandb` session has already started. "
                    "For more information on how to modify your settings with "
                    "`wandb.init()` arguments, please refer to "
                    f"{self.printer.link(wburls.get('wandb_init'), 'the W&B docs')}."
                )
                self.printer.display(line, level="warn")

        # we add this logic to be backward compatible with the old behavior of disable
        # where it would disable the service if the mode was set to disabled
        # TODO: use the regular settins object to handle this
        mode = kwargs.get("mode")
        settings_mode = (kwargs.get("settings") or {}).get("mode") or os.environ.get(
            wandb.env.MODE
        )
        settings__disable_service = (kwargs.get("settings") or {}).get(
            "_disable_service"
        ) or os.environ.get(wandb.env._DISABLE_SERVICE)

        setup_settings = {
            "mode": mode or settings_mode,
            "_disable_service": settings__disable_service,
        }

        self._wl = wandb_setup.setup(settings=setup_settings)
        # Make sure we have a logger setup (might be an early logger)
        assert self._wl is not None
        _set_logger(self._wl._get_logger())

        # Start with settings from wandb library singleton
        settings: Settings = self._wl.settings.copy()

        settings_param = kwargs.pop("settings", None)
        if settings_param is not None and isinstance(settings_param, (Settings, dict)):
            settings.update(settings_param, source=Source.INIT)

        self._setup_printer(settings)
        self._reporter = reporting.setup_reporter(settings=settings)

        sagemaker_config: Dict = (
            dict() if settings.sagemaker_disable else sagemaker.parse_sm_config()
        )
        if sagemaker_config:
            sagemaker_api_key = sagemaker_config.get("wandb_api_key", None)
            sagemaker_run, sagemaker_env = sagemaker.parse_sm_resources()
            if sagemaker_env:
                if sagemaker_api_key:
                    sagemaker_env["WANDB_API_KEY"] = sagemaker_api_key
                settings._apply_env_vars(sagemaker_env)
                wandb.setup(settings=settings)
            settings.update(sagemaker_run, source=Source.SETUP)
            with telemetry.context(obj=self._init_telemetry_obj) as tel:
                tel.feature.sagemaker = True

        with telemetry.context(obj=self._init_telemetry_obj) as tel:
            if kwargs.get("config"):
                tel.feature.set_init_config = True
            if kwargs.get("name"):
                tel.feature.set_init_name = True
            if kwargs.get("id"):
                tel.feature.set_init_id = True
            if kwargs.get("tags"):
                tel.feature.set_init_tags = True

        # Remove parameters that are not part of settings
        init_config = kwargs.pop("config", None) or dict()

        # todo: remove this once officially deprecated
        deprecated_kwargs = {
            "config_include_keys": (
                "Use `config=wandb.helper.parse_config(config_object, include=('key',))` instead."
            ),
            "config_exclude_keys": (
                "Use `config=wandb.helper.parse_config(config_object, exclude=('key',))` instead."
            ),
        }
        for deprecated_kwarg, msg in deprecated_kwargs.items():
            if kwargs.get(deprecated_kwarg):
                self.deprecated_features_used[deprecated_kwarg] = msg

        init_config = parse_config(
            init_config,
            include=kwargs.pop("config_include_keys", None),
            exclude=kwargs.pop("config_exclude_keys", None),
        )

        # merge config with sweep or sagemaker (or config file)
        self.sweep_config = dict()
        sweep_config = self._wl._sweep_config or dict()
        self.config = dict()
        self.init_artifact_config: Dict[str, Any] = dict()
        for config_data in (
            sagemaker_config,
            self._wl._config,
            init_config,
        ):
            if not config_data:
                continue
            # split out artifacts, since when inserted into
            # config they will trigger use_artifact
            # but the run is not yet upserted
            self._split_artifacts_from_config(config_data, self.config)

        if sweep_config:
            self._split_artifacts_from_config(sweep_config, self.sweep_config)

        monitor_gym = kwargs.pop("monitor_gym", None)
        if monitor_gym and len(wandb.patched["gym"]) == 0:
            wandb.gym.monitor()  # type: ignore

        if wandb.patched["tensorboard"]:
            with telemetry.context(obj=self._init_telemetry_obj) as tel:
                tel.feature.tensorboard_patch = True

        tensorboard = kwargs.pop("tensorboard", None)
        sync_tensorboard = kwargs.pop("sync_tensorboard", None)
        if tensorboard or sync_tensorboard:
            if len(wandb.patched["tensorboard"]) == 0:
                wandb.tensorboard.patch()  # type: ignore
            with telemetry.context(obj=self._init_telemetry_obj) as tel:
                tel.feature.tensorboard_sync = True

        magic = kwargs.get("magic")
        if magic not in (None, False):
            magic_install(kwargs)

        # handle login related parameters as these are applied to global state
        init_settings = {
            key: kwargs[key]
            for key in ["anonymous", "force", "mode", "resume"]
            if kwargs.get(key) is not None
        }
        if init_settings:
            settings.update(init_settings, source=Source.INIT)

        if not settings._offline and not settings._noop:
            wandb_login._login(
                anonymous=kwargs.pop("anonymous", None),
                force=kwargs.pop("force", None),
                _disable_warning=True,
                _silent=settings.quiet or settings.silent,
                _entity=kwargs.get("entity") or settings.entity,
            )

        # apply updated global state after login was handled
        wl = wandb.setup()
        assert wl is not None
        settings._apply_settings(wl.settings)

        # get status of code saving before applying user settings
        save_code_pre_user_settings = settings.save_code

        settings._apply_init(kwargs)
        if not settings._offline and not settings._noop:
            user_settings = self._wl._load_user_settings()
            settings._apply_user(user_settings)

        # ensure that user settings don't set saving to true
        # if user explicitly set these to false in UI
        if save_code_pre_user_settings is False:
            settings.update({"save_code": False}, source=Source.INIT)

        # TODO: remove this once we refactor the client. This is a temporary
        # fix to make sure that we use the same project name for wandb-core.
        # The reason this is not going throught the settings object is to
        # avoid failure cases in other parts of the code that will be
        # removed with the switch to wandb-core.
        if settings.project is None:
            project = wandb.util.auto_project_name(settings.program)
            settings.update({"project": project}, source=Source.INIT)

        # TODO(jhr): should this be moved? probably.
        settings._set_run_start_time(source=Source.INIT)

        if not settings._noop:
            self._log_setup(settings)

            if settings._jupyter:
                self._jupyter_setup(settings)
        launch_config = _handle_launch_config(settings)
        if launch_config:
            self._split_artifacts_from_config(launch_config, self.launch_config)

        self.settings = settings

        # self.settings.freeze()

    def teardown(self) -> None:
        # TODO: currently this is only called on failed wandb.init attempts
        # normally this happens on the run object
        assert logger
        logger.info("tearing down wandb.init")
        for hook in self._teardown_hooks:
            hook.call()

    def _split_artifacts_from_config(
        self, config_source: dict, config_target: dict
    ) -> None:
        for k, v in config_source.items():
            if _is_artifact_representation(v):
                self.init_artifact_config[k] = v
            else:
                config_target.setdefault(k, v)

    def _enable_logging(self, log_fname: str, run_id: Optional[str] = None) -> None:
        """Enable logging to the global debug log.

        This adds a run_id to the log, in case of multiple processes on the same machine.
        Currently, there is no way to disable logging after it's enabled.
        """
        handler = logging.FileHandler(log_fname)
        handler.setLevel(logging.INFO)

        class WBFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                record.run_id = run_id
                return True

        if run_id:
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d "
                "[%(run_id)s:%(filename)s:%(funcName)s():%(lineno)s] %(message)s"
            )
        else:
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d "
                "[%(filename)s:%(funcName)s():%(lineno)s] %(message)s"
            )

        handler.setFormatter(formatter)
        if run_id:
            handler.addFilter(WBFilter())
        assert logger is not None
        logger.propagate = False
        logger.addHandler(handler)
        # TODO: make me configurable
        logger.setLevel(logging.DEBUG)
        self._teardown_hooks.append(
            TeardownHook(
                lambda: (handler.close(), logger.removeHandler(handler)),  # type: ignore
                TeardownStage.LATE,
            )
        )

    def _safe_symlink(
        self, base: str, target: str, name: str, delete: bool = False
    ) -> None:
        # TODO(jhr): do this with relpaths, but i cant figure it out on no sleep
        if not hasattr(os, "symlink"):
            return

        pid = os.getpid()
        tmp_name = os.path.join(base, "%s.%d" % (name, pid))

        if delete:
            try:
                os.remove(os.path.join(base, name))
            except OSError:
                pass
        target = os.path.relpath(target, base)
        try:
            os.symlink(target, tmp_name)
            os.rename(tmp_name, os.path.join(base, name))
        except OSError:
            pass

    def _pause_backend(self, *args: Any, **kwargs: Any) -> None:  #  noqa
        if self.backend is None:
            return None

        # Attempt to save the code on every execution
        if self.notebook.save_ipynb():  # type: ignore
            assert self.run is not None
            res = self.run.log_code(root=None)
            logger.info("saved code: %s", res)  # type: ignore
        if self.backend.interface is not None:
            logger.info("pausing backend")  # type: ignore
            self.backend.interface.publish_pause()

    def _resume_backend(self, *args: Any, **kwargs: Any) -> None:  #  noqa
        if self.backend is not None and self.backend.interface is not None:
            logger.info("resuming backend")  # type: ignore
            self.backend.interface.publish_resume()

    def _jupyter_teardown(self) -> None:
        """Teardown hooks and display saving, called with wandb.finish."""
        assert self.notebook
        ipython = self.notebook.shell
        self.notebook.save_history()
        if self.notebook.save_ipynb():
            assert self.run is not None
            res = self.run.log_code(root=None)
            logger.info("saved code and history: %s", res)  # type: ignore
        logger.info("cleaning up jupyter logic")  # type: ignore
        # because of how we bind our methods we manually find them to unregister
        for hook in ipython.events.callbacks["pre_run_cell"]:
            if "_resume_backend" in hook.__name__:
                ipython.events.unregister("pre_run_cell", hook)
        for hook in ipython.events.callbacks["post_run_cell"]:
            if "_pause_backend" in hook.__name__:
                ipython.events.unregister("post_run_cell", hook)
        ipython.display_pub.publish = ipython.display_pub._orig_publish
        del ipython.display_pub._orig_publish

    def _jupyter_setup(self, settings: Settings) -> None:
        """Add hooks, and session history saving."""
        self.notebook = wandb.jupyter.Notebook(settings)  # type: ignore
        ipython = self.notebook.shell

        # Monkey patch ipython publish to capture displayed outputs
        if not hasattr(ipython.display_pub, "_orig_publish"):
            logger.info("configuring jupyter hooks %s", self)  # type: ignore
            ipython.display_pub._orig_publish = ipython.display_pub.publish
            # Registering resume and pause hooks

            ipython.events.register("pre_run_cell", self._resume_backend)
            ipython.events.register("post_run_cell", self._pause_backend)
            self._teardown_hooks.append(
                TeardownHook(self._jupyter_teardown, TeardownStage.EARLY)
            )

        def publish(data, metadata=None, **kwargs) -> None:  # type: ignore
            ipython.display_pub._orig_publish(data, metadata=metadata, **kwargs)
            assert self.notebook is not None
            self.notebook.save_display(
                ipython.execution_count, {"data": data, "metadata": metadata}
            )

        ipython.display_pub.publish = publish

    def _log_setup(self, settings: Settings) -> None:
        """Set up logging from settings."""
        filesystem.mkdir_exists_ok(os.path.dirname(settings.log_user))
        filesystem.mkdir_exists_ok(os.path.dirname(settings.log_internal))
        filesystem.mkdir_exists_ok(os.path.dirname(settings.sync_file))
        filesystem.mkdir_exists_ok(settings.files_dir)
        filesystem.mkdir_exists_ok(settings._tmp_code_dir)

        if settings.symlink:
            self._safe_symlink(
                os.path.dirname(settings.sync_symlink_latest),
                os.path.dirname(settings.sync_file),
                os.path.basename(settings.sync_symlink_latest),
                delete=True,
            )
            self._safe_symlink(
                os.path.dirname(settings.log_symlink_user),
                settings.log_user,
                os.path.basename(settings.log_symlink_user),
                delete=True,
            )
            self._safe_symlink(
                os.path.dirname(settings.log_symlink_internal),
                settings.log_internal,
                os.path.basename(settings.log_symlink_internal),
                delete=True,
            )

        _set_logger(logging.getLogger("wandb"))
        self._enable_logging(settings.log_user)

        assert self._wl
        assert logger

        self._wl._early_logger_flush(logger)
        logger.info(f"Logging user logs to {settings.log_user}")
        logger.info(f"Logging internal logs to {settings.log_internal}")

    def _make_run_disabled(self) -> Run:
        """Returns a Run-like object where all methods are no-ops.

        This method is used when wandb.init(mode="disabled") is called or WANDB_MODE=disabled
        is set. It creates a Run object that mimics the behavior of a normal Run but doesn't
        communicate with the W&B servers.

        The returned Run object has all expected attributes and methods, but they are
        no-op versions that don't perform any actual logging or communication.
        """
        drun = Run(settings=Settings(mode="disabled", files_dir=tempfile.gettempdir()))
        # config and summary objects
        drun._config = wandb.sdk.wandb_config.Config()
        drun._config.update(self.sweep_config)
        drun._config.update(self.config)
        drun.summary = SummaryDisabled()  # type: ignore
        # methods
        drun.log = lambda data, *_, **__: drun.summary.update(data)  # type: ignore
        drun.finish = lambda *_, **__: module.unset_globals()  # type: ignore
        drun.join = drun.finish  # type: ignore
        drun.define_metric = lambda *_, **__: wandb.sdk.wandb_metric.Metric("dummy")  # type: ignore
        drun.save = lambda *_, **__: False  # type: ignore
        for symbol in (
            "alert",
            "finish_artifact",
            "get_project_url",
            "get_sweep_url",
            "get_url",
            "link_artifact",
            "link_model",
            "use_artifact",
            "log_artifact",
            "log_code",
            "log_model",
            "use_model",
            "mark_preempting",
            "plot_table",
            "restore",
            "status",
            "watch",
            "unwatch",
            "upsert_artifact",
            "_finish",
        ):
            setattr(drun, symbol, lambda *_, **__: None)  # type: ignore
        # attributes
        drun._backend = None
        drun._step = 0
        drun._attach_id = None
        drun._run_obj = None
        drun._run_id = runid.generate_id()
        drun._name = "dummy-" + drun.id
        drun._project = "dummy"
        drun._entity = "dummy"
        drun._tags = tuple()
        drun._notes = None
        drun._group = None
        drun._start_time = time.time()
        drun._starting_step = 0
        module.set_global(
            run=drun,
            config=drun.config,
            log=drun.log,
            summary=drun.summary,
            save=drun.save,
            use_artifact=drun.use_artifact,
            log_artifact=drun.log_artifact,
            define_metric=drun.define_metric,
            plot_table=drun.plot_table,
            alert=drun.alert,
        )
        return drun

    def _on_progress_init(self, handle: MailboxProgress) -> None:
        assert self.printer
        line = "Waiting for wandb.init()...\r"
        percent_done = handle.percent_done
        self.printer.progress_update(line, percent_done=percent_done)

    def init(self) -> Run:  # noqa: C901
        if logger is None:
            raise RuntimeError("Logger not initialized")
        logger.info("calling init triggers")
        trigger.call("on_init", **self.kwargs)  # type: ignore

        assert self.settings is not None
        assert self._wl is not None
        assert self._reporter is not None

        logger.info(
            f"wandb.init called with sweep_config: {self.sweep_config}\nconfig: {self.config}"
        )

        if self.settings._noop:
            return self._make_run_disabled()
        if self.settings.reinit or (
            self.settings._jupyter and self.settings.reinit is not False
        ):
            if len(self._wl._global_run_stack) > 0:
                if len(self._wl._global_run_stack) > 1:
                    wandb.termwarn(
                        "If you want to track multiple runs concurrently in wandb, "
                        "you should use multi-processing not threads"
                    )

                latest_run = self._wl._global_run_stack[-1]

                logger.info(
                    f"re-initializing run, found existing run on stack: {latest_run._run_id}"
                )

                jupyter = self.settings._jupyter
                if jupyter and not self.settings.silent:
                    ipython.display_html(
                        f"Finishing last run (ID:{latest_run._run_id}) before initializing another..."
                    )

                latest_run.finish()

                if jupyter and not self.settings.silent:
                    ipython.display_html(
                        f"Successfully finished last run (ID:{latest_run._run_id}). Initializing new run:<br/>"
                    )
        elif isinstance(wandb.run, Run):
            service = self._wl.service
            # We shouldn't return a stale global run if we are in a new pid
            if not service or os.getpid() == wandb.run._init_pid:
                logger.info("wandb.init() called when a run is still active")
                with telemetry.context() as tel:
                    tel.feature.init_return_run = True
                return wandb.run

        logger.info("starting backend")

        service = self._wl.service
        if service:
            logger.info("sending inform_init request")
            service.inform_init(
                settings=self.settings.to_proto(),
                run_id=self.settings.run_id,
            )

        mailbox = Mailbox()
        backend = Backend(
            settings=self.settings,
            service=service,
            mailbox=mailbox,
        )
        backend.ensure_launched()
        logger.info("backend started and connected")
        # Make sure we are logged in
        # wandb_login._login(_backend=backend, _settings=self.settings)

        # resuming needs access to the server, check server_status()?
        run = Run(
            config=self.config,
            settings=self.settings,
            sweep_config=self.sweep_config,
            launch_config=self.launch_config,
        )

        # Populate initial telemetry
        with telemetry.context(run=run, obj=self._init_telemetry_obj) as tel:
            tel.cli_version = wandb.__version__
            tel.python_version = platform.python_version()
            tel.platform = f"{platform.system()}-{platform.machine()}".lower()
            hf_version = _huggingface_version()
            if hf_version:
                tel.huggingface_version = hf_version
            if self.settings._jupyter:
                tel.env.jupyter = True
            if self.settings._ipython:
                tel.env.ipython = True
            if self.settings._colab:
                tel.env.colab = True
            if self.settings._kaggle:
                tel.env.kaggle = True
            if self.settings._windows:
                tel.env.windows = True

            if self.settings.launch:
                tel.feature.launch = True

            for module_name in telemetry.list_telemetry_imports(only_imported=True):
                setattr(tel.imports_init, module_name, True)

            # probe the active start method
            active_start_method: Optional[str] = None
            if self.settings.start_method == "thread":
                active_start_method = self.settings.start_method
            else:
                active_start_method = getattr(
                    backend._multiprocessing, "get_start_method", lambda: None
                )()

            if active_start_method == "spawn":
                tel.env.start_spawn = True
            elif active_start_method == "fork":
                tel.env.start_fork = True
            elif active_start_method == "forkserver":
                tel.env.start_forkserver = True
            elif active_start_method == "thread":
                tel.env.start_thread = True

            if os.environ.get("PEX"):
                tel.env.pex = True

            if self.settings._aws_lambda:
                tel.env.aws_lambda = True

            if os.environ.get(wandb.env._DISABLE_SERVICE):
                tel.feature.service_disabled = True

            if service:
                tel.feature.service = True
            if self.settings._flow_control_disabled:
                tel.feature.flow_control_disabled = True
            if self.settings._flow_control_custom:
                tel.feature.flow_control_custom = True
            if not self.settings._require_legacy_service:
                tel.feature.core = True
            if self.settings._shared:
                wandb.termwarn(
                    "The `_shared` feature is experimental and may change. "
                    "Please contact support@wandb.com for guidance and to report any issues."
                )
                tel.feature.shared_mode = True

            tel.env.maybe_mp = _maybe_mp_process(backend)

        if not self.settings.label_disable:
            if self.notebook:
                run._label_probe_notebook(self.notebook)
            else:
                run._label_probe_main()

        for deprecated_feature, msg in self.deprecated_features_used.items():
            warning_message = f"`{deprecated_feature}` is deprecated. {msg}"
            deprecate(
                field_name=getattr(Deprecated, "init__" + deprecated_feature),
                warning_message=warning_message,
                run=run,
            )

        logger.info("updated telemetry")

        run._set_library(self._wl)
        run._set_backend(backend)
        run._set_reporter(self._reporter)
        run._set_teardown_hooks(self._teardown_hooks)

        backend._hack_set_run(run)
        assert backend.interface
        mailbox.enable_keepalive()
        backend.interface.publish_header()

        # Using GitRepo() blocks & can be slow, depending on user's current git setup.
        # We don't want to block run initialization/start request, so populate run's git
        # info beforehand.
        if not self.settings.disable_git:
            run._populate_git_info()

        run_result: Optional[pb.RunUpdateResult] = None

        if self.settings._offline:
            with telemetry.context(run=run) as tel:
                tel.feature.offline = True

            if self.settings.resume:
                wandb.termwarn(
                    "`resume` will be ignored since W&B syncing is set to `offline`. "
                    f"Starting a new run with run id {run.id}."
                )
        error: Optional[wandb.errors.Error] = None

        timeout = self.settings.init_timeout

        logger.info(f"communicating run to backend with {timeout} second timeout")

        run_init_handle = backend.interface.deliver_run(run)
        result = run_init_handle.wait(
            timeout=timeout,
            on_progress=self._on_progress_init,
            cancel=True,
        )
        if result:
            run_result = result.run_result

        if run_result is None:
            error_message = (
                f"Run initialization has timed out after {timeout} sec. "
                f"\nPlease refer to the documentation for additional information: {wburls.get('doc_start_err')}"
            )
            # We're not certain whether the error we encountered is due to an issue
            # with the server (a "CommError") or if it's a problem within the SDK (an "Error").
            # This means that the error could be a result of the server being unresponsive,
            # or it could be because we were unable to communicate with the wandb service.
            error = CommError(error_message)
            run_init_handle._cancel()
        elif run_result.HasField("error"):
            error = ProtobufErrorHandler.to_exception(run_result.error)

        if error is not None:
            logger.error(f"encountered error: {error}")
            if not service:
                # Shutdown the backend and get rid of the logger
                # we don't need to do console cleanup at this point
                backend.cleanup()
                self.teardown()
            raise error

        assert run_result is not None  # for mypy

        if not run_result.HasField("run"):
            raise Error(
                "It appears that something have gone wrong during the program execution as an unexpected missing field was encountered. "
                "(run_result is missing the 'run' field)"
            )

        if run_result.run.resumed:
            logger.info("run resumed")
            with telemetry.context(run=run) as tel:
                tel.feature.resumed = run_result.run.resumed

        run._set_run_obj(run_result.run)

        run._on_init()

        logger.info("starting run threads in backend")
        # initiate run (stats and metadata probing)

        if service:
            service.inform_start(
                settings=self.settings.to_proto(),
                run_id=self.settings.run_id,
            )

        assert backend.interface
        assert run._run_obj

        run_start_handle = backend.interface.deliver_run_start(run._run_obj)
        # TODO: add progress to let user know we are doing something
        run_start_result = run_start_handle.wait(timeout=30)
        if run_start_result is None:
            run_start_handle.abandon()

        assert self._wl is not None
        self._wl._global_run_stack.append(run)
        self.run = run

        run._handle_launch_artifact_overrides()
        if (
            self.settings.launch
            and self.settings.launch_config_path
            and os.path.exists(self.settings.launch_config_path)
        ):
            run.save(self.settings.launch_config_path)
        # put artifacts in run config here
        # since doing so earlier will cause an error
        # as the run is not upserted
        for k, v in self.init_artifact_config.items():
            run.config.update({k: v}, allow_val_change=True)
        job_artifact = run._launch_artifact_mapping.get(
            wandb.util.LAUNCH_JOB_ARTIFACT_SLOT_NAME
        )
        if job_artifact:
            run.use_artifact(job_artifact)

        self.backend = backend
        assert self._reporter
        self._reporter.set_context(run=run)
        run._on_start()
        logger.info("run started, returning control to user process")
        return run


def _attach(
    attach_id: Optional[str] = None,
    run_id: Optional[str] = None,
    *,
    run: Optional["Run"] = None,
) -> Optional[Run]:
    """Attach to a run currently executing in another process/thread.

    Arguments:
        attach_id: (str, optional) The id of the run or an attach identifier
            that maps to a run.
        run_id: (str, optional) The id of the run to attach to.
        run: (Run, optional) The run instance to attach
    """
    attach_id = attach_id or run_id
    if not ((attach_id is None) ^ (run is None)):
        raise UsageError("Either (`attach_id` or `run_id`) or `run` must be specified")

    attach_id = attach_id or (run._attach_id if run else None)

    if attach_id is None:
        raise UsageError(
            "Either `attach_id` or `run_id` must be specified or `run` must have `_attach_id`"
        )
    wandb._assert_is_user_process()  # type: ignore

    _wl = wandb_setup._setup()
    assert _wl

    _set_logger(_wl._get_logger())
    if logger is None:
        raise UsageError("logger is not initialized")

    service = _wl.service
    if not service:
        raise UsageError(f"Unable to attach to run {attach_id} (no service process)")

    try:
        attach_settings = service.inform_attach(attach_id=attach_id)
    except Exception as e:
        raise UsageError(f"Unable to attach to run {attach_id}") from e

    settings: Settings = copy.copy(_wl._settings)

    settings.update(
        {
            "run_id": attach_id,
            "_start_time": attach_settings._start_time.value,
            "_start_datetime": attach_settings._start_datetime.value,
            "_offline": attach_settings._offline.value,
        },
        source=Source.INIT,
    )

    # TODO: consolidate this codepath with wandb.init()
    mailbox = Mailbox()
    backend = Backend(settings=settings, service=service, mailbox=mailbox)
    backend.ensure_launched()
    logger.info("attach backend started and connected")

    if run is None:
        run = Run(settings=settings)
    else:
        run._init(settings=settings)
    run._set_library(_wl)
    run._set_backend(backend)
    backend._hack_set_run(run)
    assert backend.interface

    mailbox.enable_keepalive()

    attach_handle = backend.interface.deliver_attach(attach_id)
    # TODO: add progress to let user know we are doing something
    attach_result = attach_handle.wait(timeout=30)
    if not attach_result:
        attach_handle.abandon()
        raise UsageError("Timeout attaching to run")
    attach_response = attach_result.response.attach_response
    if attach_response.error and attach_response.error.message:
        raise UsageError(f"Failed to attach to run: {attach_response.error.message}")

    run._set_run_obj(attach_response.run)
    run._on_attach()
    return run


def init(
    job_type: Optional[str] = None,
    dir: Optional[StrPath] = None,
    config: Union[Dict, str, None] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    reinit: Optional[bool] = None,
    tags: Optional[Sequence] = None,
    group: Optional[str] = None,
    name: Optional[str] = None,
    notes: Optional[str] = None,
    magic: Optional[Union[dict, str, bool]] = None,
    config_exclude_keys: Optional[List[str]] = None,
    config_include_keys: Optional[List[str]] = None,
    anonymous: Optional[str] = None,
    mode: Optional[str] = None,
    allow_val_change: Optional[bool] = None,
    resume: Optional[Union[bool, str]] = None,
    force: Optional[bool] = None,
    tensorboard: Optional[bool] = None,  # alias for sync_tensorboard
    sync_tensorboard: Optional[bool] = None,
    monitor_gym: Optional[bool] = None,
    save_code: Optional[bool] = None,
    id: Optional[str] = None,
    fork_from: Optional[str] = None,
    resume_from: Optional[str] = None,
    settings: Union[Settings, Dict[str, Any], None] = None,
) -> Run:
    r"""Start a new run to track and log to W&B.

    In an ML training pipeline, you could add `wandb.init()`
    to the beginning of your training script as well as your evaluation
    script, and each piece would be tracked as a run in W&B.

    `wandb.init()` spawns a new background process to log data to a run, and it
    also syncs data to wandb.ai by default, so you can see live visualizations.

    Call `wandb.init()` to start a run before logging data with `wandb.log()`:
    <!--yeadoc-test:init-method-log-->
    ```python
    import wandb

    wandb.init()
    # ... calculate metrics, generate media
    wandb.log({"accuracy": 0.9})
    ```

    `wandb.init()` returns a run object, and you can also access the run object
    via `wandb.run`:
    <!--yeadoc-test:init-and-assert-global-->
    ```python
    import wandb

    run = wandb.init()

    assert run is wandb.run
    ```

    At the end of your script, we will automatically call `wandb.finish` to
    finalize and cleanup the run. However, if you call `wandb.init` from a
    child process, you must explicitly call `wandb.finish` at the end of the
    child process.

    For more on using `wandb.init()`, including detailed examples, check out our
    [guide and FAQs](https://docs.wandb.ai/guides/track/launch).

    Arguments:
        project: (str, optional) The name of the project where you're sending
            the new run. If the project is not specified, we will try to infer
            the project name from git root or the current program file. If we
            can't infer the project name, we will default to `"uncategorized"`.
        entity: (str, optional) An entity is a username or team name where
            you're sending runs. This entity must exist before you can send runs
            there, so make sure to create your account or team in the UI before
            starting to log runs.
            If you don't specify an entity, the run will be sent to your default
            entity. Change your default entity
            in [your settings](https://wandb.ai/settings) under "default location
            to create new projects".
        config: (dict, argparse, absl.flags, str, optional)
            This sets `wandb.config`, a dictionary-like object for saving inputs
            to your job, like hyperparameters for a model or settings for a data
            preprocessing job. The config will show up in a table in the UI that
            you can use to group, filter, and sort runs. Keys should not contain
            `.` in their names, and values should be under 10 MB.
            If dict, argparse or absl.flags: will load the key value pairs into
                the `wandb.config` object.
            If str: will look for a yaml file by that name, and load config from
                that file into the `wandb.config` object.
        save_code: (bool, optional) Turn this on to save the main script or
            notebook to W&B. This is valuable for improving experiment
            reproducibility and to diff code across experiments in the UI. By
            default this is off, but you can flip the default behavior to on
            in [your settings page](https://wandb.ai/settings).
        group: (str, optional) Specify a group to organize individual runs into
            a larger experiment. For example, you might be doing cross
            validation, or you might have multiple jobs that train and evaluate
            a model against different test sets. Group gives you a way to
            organize runs together into a larger whole, and you can toggle this
            on and off in the UI. For more details, see our
            [guide to grouping runs](https://docs.wandb.com/guides/runs/grouping).
        job_type: (str, optional) Specify the type of run, which is useful when
            you're grouping runs together into larger experiments using group.
            For example, you might have multiple jobs in a group, with job types
            like train and eval. Setting this makes it easy to filter and group
            similar runs together in the UI so you can compare apples to apples.
        tags: (list, optional) A list of strings, which will populate the list
            of tags on this run in the UI. Tags are useful for organizing runs
            together, or applying temporary labels like "baseline" or
            "production". It's easy to add and remove tags in the UI, or filter
            down to just runs with a specific tag.
            If you are resuming a run, its tags will be overwritten by the tags
            you pass to `wandb.init()`. If you want to add tags to a resumed run
            without overwriting its existing tags, use `run.tags += ["new_tag"]`
            after `wandb.init()`.
        name: (str, optional) A short display name for this run, which is how
            you'll identify this run in the UI. By default, we generate a random
            two-word name that lets you easily cross-reference runs from the
            table to charts. Keeping these run names short makes the chart
            legends and tables easier to read. If you're looking for a place to
            save your hyperparameters, we recommend saving those in config.
        notes: (str, optional) A longer description of the run, like a `-m` commit
            message in git. This helps you remember what you were doing when you
            ran this run.
        dir: (str or pathlib.Path, optional) An absolute path to a directory where
            metadata will be stored. When you call `download()` on an artifact,
            this is the directory where downloaded files will be saved. By default,
            this is the `./wandb` directory.
        resume: (bool, str, optional) Sets the resuming behavior. Options:
            `"allow"`, `"must"`, `"never"`, `"auto"` or `None`. Defaults to `None`.
            Cases:
            - `None` (default): If the new run has the same ID as a previous run,
                this run overwrites that data.
            - `"auto"` (or `True`): if the previous run on this machine crashed,
                automatically resume it. Otherwise, start a new run.
            - `"allow"`: if id is set with `init(id="UNIQUE_ID")` or
                `WANDB_RUN_ID="UNIQUE_ID"` and it is identical to a previous run,
                wandb will automatically resume the run with that id. Otherwise,
                wandb will start a new run.
            - `"never"`: if id is set with `init(id="UNIQUE_ID")` or
                `WANDB_RUN_ID="UNIQUE_ID"` and it is identical to a previous run,
                wandb will crash.
            - `"must"`: if id is set with `init(id="UNIQUE_ID")` or
                `WANDB_RUN_ID="UNIQUE_ID"` and it is identical to a previous run,
                wandb will automatically resume the run with the id. Otherwise,
                wandb will crash.
            See [our guide to resuming runs](https://docs.wandb.com/guides/runs/resuming)
            for more.
        reinit: (bool, optional) Allow multiple `wandb.init()` calls in the same
            process. (default: `False`)
        magic: (bool, dict, or str, optional) The bool controls whether we try to
            auto-instrument your script, capturing basic details of your run
            without you having to add more wandb code. (default: `False`)
            You can also pass a dict, json string, or yaml filename.
        config_exclude_keys: (list, optional) string keys to exclude from
            `wandb.config`.
        config_include_keys: (list, optional) string keys to include in
            `wandb.config`.
        anonymous: (str, optional) Controls anonymous data logging. Options:
            - `"never"` (default): requires you to link your W&B account before
                tracking the run, so you don't accidentally create an anonymous
                run.
            - `"allow"`: lets a logged-in user track runs with their account, but
                lets someone who is running the script without a W&B account see
                the charts in the UI.
            - `"must"`: sends the run to an anonymous account instead of to a
                signed-up user account.
        mode: (str, optional) Can be `"online"`, `"offline"` or `"disabled"`. Defaults to
            online.
        allow_val_change: (bool, optional) Whether to allow config values to
            change after setting the keys once. By default, we throw an exception
            if a config value is overwritten. If you want to track something
            like a varying learning rate at multiple times during training, use
            `wandb.log()` instead. (default: `False` in scripts, `True` in Jupyter)
        force: (bool, optional) If `True`, this crashes the script if a user isn't
            logged in to W&B. If `False`, this will let the script run in offline
            mode if a user isn't logged in to W&B. (default: `False`)
        sync_tensorboard: (bool, optional) Synchronize wandb logs from tensorboard or
            tensorboardX and save the relevant events file. (default: `False`)
        tensorboard: (bool, optional) Alias for `sync_tensorboard`, deprecated.
        monitor_gym: (bool, optional) Automatically log videos of environment when
            using OpenAI Gym. (default: `False`)
            See [our guide to this integration](https://docs.wandb.com/guides/integrations/openai-gym).
        id: (str, optional) A unique ID for this run, used for resuming. It must
            be unique in the project, and if you delete a run you can't reuse
            the ID. Use the `name` field for a short descriptive name, or `config`
            for saving hyperparameters to compare across runs. The ID cannot
            contain the following special characters: `/\#?%:`.
            See [our guide to resuming runs](https://docs.wandb.com/guides/runs/resuming).
        fork_from: (str, optional) A string with the format {run_id}?_step={step} describing
            a moment in a previous run to fork a new run from. Creates a new run that picks up
            logging history from the specified run at the specified moment. The target run must
            be in the current project. Example: `fork_from="my-run-id?_step=1234"`.
        resume_from: (str, optional) A string with the format {run_id}?_step={step} describing
            a moment in a previous run to resume a run from. This allows users to truncate
            the history logged to a run at an intermediate step and resume logging from that step.
            It uses run forking under the hood. The target run must be in the
            current project. Example: `resume_from="my-run-id?_step=1234"`.
        settings: (dict, wandb.Settings, optional) Settings to use for this run. (default: None)

    Examples:
    ### Set where the run is logged

    You can change where the run is logged, just like changing
    the organization, repository, and branch in git:
    ```python
    import wandb

    user = "geoff"
    project = "capsules"
    display_name = "experiment-2021-10-31"

    wandb.init(entity=user, project=project, name=display_name)
    ```

    ### Add metadata about the run to the config

    Pass a dictionary-style object as the `config` keyword argument to add
    metadata, like hyperparameters, to your run.
    <!--yeadoc-test:init-set-config-->
    ```python
    import wandb

    config = {"lr": 3e-4, "batch_size": 32}
    config.update({"architecture": "resnet", "depth": 34})
    wandb.init(config=config)
    ```

    Raises:
        Error: if some unknown or internal error happened during the run initialization.
        AuthenticationError: if the user failed to provide valid credentials.
        CommError: if there was a problem communicating with the WandB server.
        UsageError: if the user provided invalid arguments.
        KeyboardInterrupt: if user interrupts the run.

    Returns:
        A `Run` object.
    """
    wandb._assert_is_user_process()  # type: ignore

    kwargs = dict(locals())

    num_resume_options_set = (
        (fork_from is not None)  # wrap
        + (resume is not None)
        + (resume_from is not None)
    )
    if num_resume_options_set > 1:
        raise ValueError(
            "You cannot specify more than one of `fork_from`, `resume`, or `resume_from`"
        )

    try:
        wi = _WandbInit()
        wi.setup(kwargs)
        return wi.init()

    except KeyboardInterrupt as e:
        if logger is not None:
            logger.warning("interrupted", exc_info=e)

        raise

    except Exception as e:
        if logger is not None:
            logger.exception("error in wandb.init()", exc_info=e)

        # Need to build delay into this sentry capture because our exit hooks
        # mess with sentry's ability to send out errors before the program ends.
        wandb._sentry.reraise(e)
        raise AssertionError()  # unreachable
