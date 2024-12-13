"""Defines wandb.init() and associated classes and methods.

`wandb.init()` indicates the beginning of a new run. In an ML training pipeline,
you could add `wandb.init()` to the beginning of your training script as well as
your evaluation script, and each step would be tracked as a run in W&B.

For more on using `wandb.init()`, including code snippets, check out our
[guide and FAQs](https://docs.wandb.ai/guides/track/launch).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import platform
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Any, Literal, Sequence

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

import wandb
import wandb.env
from wandb import trigger
from wandb.errors import CommError, Error, UsageError
from wandb.errors.links import url_registry
from wandb.errors.util import ProtobufErrorHandler
from wandb.integration import sagemaker
from wandb.sdk.lib import runid
from wandb.sdk.lib.paths import StrPath
from wandb.util import _is_artifact_representation

from . import wandb_login, wandb_setup
from .backend.backend import Backend
from .lib import SummaryDisabled, filesystem, module, printer, telemetry
from .lib.deprecate import Deprecated, deprecate
from .lib.mailbox import Mailbox, MailboxProgress
from .wandb_helper import parse_config
from .wandb_run import Run, TeardownHook, TeardownStage
from .wandb_settings import Settings

if TYPE_CHECKING:
    from wandb.proto import wandb_internal_pb2 as pb

logger: logging.Logger | None = None  # logger configured during wandb.init()


def _set_logger(log_object: logging.Logger) -> None:
    """Configure module logger."""
    global logger
    logger = log_object


def _huggingface_version() -> str | None:
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


def _handle_launch_config(settings: Settings) -> dict[str, Any]:
    launch_run_config: dict[str, Any] = {}
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
        self.settings: Settings | None = None
        self.sweep_config: dict[str, Any] = {}
        self.launch_config: dict[str, Any] = {}
        self.config: dict[str, Any] = {}
        self.run: Run | None = None
        self.backend: Backend | None = None

        self._teardown_hooks: list[TeardownHook] = []
        self._wl: wandb_setup._WandbSetup | None = None
        self.notebook: wandb.jupyter.Notebook | None = None  # type: ignore
        self.printer = printer.new_printer()

        self._init_telemetry_obj = telemetry.TelemetryRecord()

        self.deprecated_features_used: dict[str, str] = dict()

    def warn_env_vars_change_after_setup(self) -> None:
        """Warn if environment variables change after wandb singleton is initialized.

        Any settings from environment variables set after the singleton is initialized
        (via login/setup/etc.) will be ignored.
        """
        singleton = wandb_setup._WandbSetup._instance
        if singleton is None:
            return

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
                f"{self.printer.link(url_registry.url('wandb-init'), 'the W&B docs')}."
            )
            self.printer.display(line, level="warn")

    def setup(  # noqa: C901
        self,
        init_settings: Settings,
        config: dict | str | None = None,
        config_exclude_keys: list[str] | None = None,
        config_include_keys: list[str] | None = None,
        allow_val_change: bool | None = None,
        monitor_gym: bool | None = None,
    ) -> None:
        """Complete setup for `wandb.init()`.

        This includes parsing all arguments, applying them with settings and enabling logging.
        """
        self.warn_env_vars_change_after_setup()

        # mode="disabled" is a special case where we don't want to start wandb-core
        setup_settings_dict: dict[str, Any] = {}
        if init_settings.mode == "disabled":
            setup_settings_dict["mode"] = init_settings.mode
        # TODO: x_disable_service is deprecated, remove this once officially deprecated
        if init_settings.x_disable_service:
            setup_settings_dict["x_disable_service"] = init_settings.x_disable_service
        setup_settings = (
            wandb.Settings(**setup_settings_dict) if setup_settings_dict else None
        )

        self._wl = wandb_setup.setup(settings=setup_settings)

        assert self._wl is not None
        _set_logger(self._wl._get_logger())

        # Start with settings from wandb library singleton
        settings = self._wl.settings.copy()

        # handle custom sweep- and launch-related logic for init settings
        if settings.sweep_id:
            init_settings.sweep_id = settings.sweep_id
            init_settings.handle_sweep_logic()
        if settings.launch:
            init_settings.launch = settings.launch
            init_settings.handle_launch_logic()

        # Apply settings from wandb.init() call
        settings.update_from_settings(init_settings)

        sagemaker_config: dict = (
            dict() if settings.sagemaker_disable else sagemaker.parse_sm_config()
        )
        if sagemaker_config:
            sagemaker_api_key = sagemaker_config.get("wandb_api_key", None)
            sagemaker_run, sagemaker_env = sagemaker.parse_sm_resources()
            if sagemaker_env:
                if sagemaker_api_key:
                    sagemaker_env["WANDB_API_KEY"] = sagemaker_api_key
                settings.update_from_env_vars(sagemaker_env)
                wandb.setup(settings=settings)
            settings.update_from_dict(sagemaker_run)
            with telemetry.context(obj=self._init_telemetry_obj) as tel:
                tel.feature.sagemaker = True

        with telemetry.context(obj=self._init_telemetry_obj) as tel:
            if config is not None:
                tel.feature.set_init_config = True
            if settings.run_name is not None:
                tel.feature.set_init_name = True
            if settings.run_id is not None:
                tel.feature.set_init_id = True
            if settings.run_tags is not None:
                tel.feature.set_init_tags = True

        # TODO: remove this once officially deprecated
        if config_exclude_keys:
            self.deprecated_features_used["config_exclude_keys"] = (
                "Use `config=wandb.helper.parse_config(config_object, exclude=('key',))` instead."
            )
        if config_include_keys:
            self.deprecated_features_used["config_include_keys"] = (
                "Use `config=wandb.helper.parse_config(config_object, include=('key',))` instead."
            )
        config = parse_config(
            config or dict(),
            include=config_include_keys,
            exclude=config_exclude_keys,
        )

        # merge config with sweep or sagemaker (or config file)
        self.sweep_config = dict()
        sweep_config = self._wl._sweep_config or dict()
        self.config = dict()
        self.init_artifact_config: dict[str, Any] = dict()
        for config_data in (
            sagemaker_config,
            self._wl._config,
            config,
        ):
            if not config_data:
                continue
            # split out artifacts, since when inserted into
            # config they will trigger use_artifact
            # but the run is not yet upserted
            self._split_artifacts_from_config(config_data, self.config)  # type: ignore

        if sweep_config:
            self._split_artifacts_from_config(sweep_config, self.sweep_config)

        if monitor_gym and len(wandb.patched["gym"]) == 0:
            wandb.gym.monitor()  # type: ignore

        if wandb.patched["tensorboard"]:
            with telemetry.context(obj=self._init_telemetry_obj) as tel:
                tel.feature.tensorboard_patch = True

        if settings.sync_tensorboard:
            if len(wandb.patched["tensorboard"]) == 0:
                wandb.tensorboard.patch()  # type: ignore
            with telemetry.context(obj=self._init_telemetry_obj) as tel:
                tel.feature.tensorboard_sync = True

        if not settings._offline and not settings._noop:
            wandb_login._login(
                anonymous=settings.anonymous,
                force=settings.force,
                _disable_warning=True,
                _silent=settings.quiet or settings.silent,
                _entity=settings.entity,
            )

        # apply updated global state after login was handled
        wl = wandb.setup()
        assert wl is not None
        login_settings = {
            k: v
            for k, v in {
                "anonymous": wl.settings.anonymous,
                "api_key": wl.settings.api_key,
                "base_url": wl.settings.base_url,
                "force": wl.settings.force,
                "login_timeout": wl.settings.login_timeout,
            }.items()
            if v is not None
        }
        if login_settings:
            settings.update_from_dict(login_settings)

        # handle custom resume logic
        settings.handle_resume_logic()

        # get status of code saving before applying user settings
        save_code_pre_user_settings = settings.save_code
        if not settings._offline and not settings._noop:
            user_settings = self._wl._load_user_settings()
            if user_settings is not None:
                settings.update_from_dict(user_settings)

        # ensure that user settings don't set saving to true
        # if user explicitly set these to false in UI
        if save_code_pre_user_settings is False:
            settings.save_code = False

        # TODO: remove this once we refactor the client. This is a temporary
        # fix to make sure that we use the same project name for wandb-core.
        # The reason this is not going throught the settings object is to
        # avoid failure cases in other parts of the code that will be
        # removed with the switch to wandb-core.
        if settings.project is None:
            settings.project = wandb.util.auto_project_name(settings.program)

        settings.x_start_time = time.time()

        if not settings._noop:
            self._log_setup(settings)

            if settings._jupyter:
                self._jupyter_setup(settings)
        launch_config = _handle_launch_config(settings)
        if launch_config:
            self._split_artifacts_from_config(launch_config, self.launch_config)

        self.settings = settings

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

    def _enable_logging(self, log_fname: str, run_id: str | None = None) -> None:
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
        tmp_name = os.path.join(base, f"{name}.{pid}")

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
        run_id = runid.generate_id()
        drun = Run(
            settings=Settings(
                mode="disabled",
                x_files_dir=tempfile.gettempdir(),
                run_id=run_id,
                run_tags=tuple(),
                run_notes=None,
                run_group=None,
                run_name=f"dummy-{run_id}",
                project="dummy",
                entity="dummy",
            )
        )
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
            "log_code",
            "log_model",
            "use_model",
            "mark_preempting",
            "restore",
            "status",
            "watch",
            "unwatch",
            "upsert_artifact",
            "_finish",
        ):
            setattr(drun, symbol, lambda *_, **__: None)  # type: ignore

        class _ChainableNoOp:
            """An object that allows chaining arbitrary attributes and method calls."""

            def __getattr__(self, _: str) -> Self:
                return self

            def __call__(self, *_: Any, **__: Any) -> Self:
                return self

        class _ChainableNoOpField:
            # This is used to chain arbitrary attributes and method calls.
            # For example, `run.log_artifact().state` will work in disabled mode.
            def __init__(self) -> None:
                self._value = None

            def __set__(self, instance: Any, value: Any) -> None:
                self._value = value

            def __get__(self, instance: Any, owner: type) -> Any:
                return _ChainableNoOp() if (self._value is None) else self._value

            def __call__(self, *args: Any, **kwargs: Any) -> _ChainableNoOp:
                return _ChainableNoOp()

        drun.log_artifact = _ChainableNoOpField()
        # attributes
        drun._start_time = time.time()
        drun._starting_step = 0
        drun._step = 0
        drun._attach_id = None
        drun._backend = None

        # set the disabled run as the global run
        module.set_global(
            run=drun,
            config=drun.config,
            log=drun.log,
            summary=drun.summary,
            save=drun.save,
            use_artifact=drun.use_artifact,
            log_artifact=drun.log_artifact,
            define_metric=drun.define_metric,
            alert=drun.alert,
            watch=drun.watch,
            unwatch=drun.unwatch,
        )
        return drun

    def _on_progress_init(self, handle: MailboxProgress) -> None:
        line = "Waiting for wandb.init()...\r"
        percent_done = handle.percent_done
        self.printer.progress_update(line, percent_done=percent_done)

    def init(self) -> Run:  # noqa: C901
        if logger is None:
            raise RuntimeError("Logger not initialized")
        logger.info("calling init triggers")
        trigger.call("on_init")

        assert self.settings is not None
        assert self._wl is not None

        logger.info(
            f"wandb.init called with sweep_config: {self.sweep_config}\nconfig: {self.config}"
        )

        if self.settings._noop:
            return self._make_run_disabled()
        if (
            self.settings.reinit
            or (self.settings._jupyter and self.settings.reinit is not False)
        ) and len(self._wl._global_run_stack) > 0:
            if len(self._wl._global_run_stack) > 1:
                wandb.termwarn(
                    "Launching multiple wandb runs using Python's threading"
                    " module is not well-supported."
                    " Please use multiprocessing instead."
                    " Finishing previous run before initializing another."
                )

            latest_run = self._wl._global_run_stack[-1]
            logger.info(f"found existing run on stack: {latest_run._run_id}")
            latest_run.finish()
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
                run_id=self.settings.run_id,  # type: ignore
            )

        mailbox = Mailbox()
        backend = Backend(
            settings=self.settings,
            service=service,
            mailbox=mailbox,
        )
        backend.ensure_launched()
        logger.info("backend started and connected")

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
            active_start_method: str | None = None
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
            if self.settings.x_flow_control_disabled:
                tel.feature.flow_control_disabled = True
            if self.settings.x_flow_control_custom:
                tel.feature.flow_control_custom = True
            if not self.settings.x_require_legacy_service:
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
        run._set_teardown_hooks(self._teardown_hooks)

        backend._hack_set_run(run)
        assert backend.interface
        mailbox.enable_keepalive()
        backend.interface.publish_header()

        # Using GitRepo() blocks & can be slow, depending on user's current git setup.
        # We don't want to block run initialization/start request, so populate run's git
        # info beforehand.
        if not (self.settings.disable_git or self.settings.x_disable_machine_info):
            run._populate_git_info()

        run_result: pb.RunUpdateResult | None = None

        if self.settings._offline:
            with telemetry.context(run=run) as tel:
                tel.feature.offline = True

            if self.settings.resume:
                wandb.termwarn(
                    "`resume` will be ignored since W&B syncing is set to `offline`. "
                    f"Starting a new run with run id {run.id}."
                )
        error: wandb.Error | None = None

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
                "Please try increasing the timeout with the `init_timeout` setting: "
                "`wandb.init(settings=wandb.Settings(init_timeout=120))`."
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
                "It appears that something have gone wrong during the program "
                "execution as an unexpected missing field was encountered. "
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
            assert self.settings.run_id
            service.inform_start(
                settings=self.settings.to_proto(),
                run_id=self.settings.run_id,
            )

        assert backend.interface

        run_start_handle = backend.interface.deliver_run_start(run)
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
        run._on_start()
        logger.info("run started, returning control to user process")
        return run


def _attach(
    attach_id: str | None = None,
    run_id: str | None = None,
    *,
    run: Run | None = None,
) -> Run | None:
    """Attach to a run currently executing in another process/thread.

    Args:
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

    settings.update_from_dict(
        {
            "run_id": attach_id,
            "x_start_time": attach_settings.x_start_time.value,
            "mode": attach_settings.mode.value,
        }
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


def init(  # noqa: C901
    entity: str | None = None,
    project: str | None = None,
    dir: StrPath | None = None,
    id: str | None = None,
    name: str | None = None,
    notes: str | None = None,
    tags: Sequence[str] | None = None,
    config: dict[str, Any] | str | None = None,
    config_exclude_keys: list[str] | None = None,
    config_include_keys: list[str] | None = None,
    allow_val_change: bool | None = None,
    group: str | None = None,
    job_type: str | None = None,
    mode: Literal["online", "offline", "disabled"] | None = None,
    force: bool | None = None,
    anonymous: Literal["never", "allow", "must"] | None = None,
    reinit: bool | None = None,
    resume: bool | Literal["allow", "never", "must", "auto"] | None = None,
    resume_from: str | None = None,
    fork_from: str | None = None,
    save_code: bool | None = None,
    tensorboard: bool | None = None,
    sync_tensorboard: bool | None = None,
    monitor_gym: bool | None = None,
    settings: Settings | dict[str, Any] | None = None,
) -> Run:
    r"""Start a new run to track and log to W&B.

    In an ML training pipeline, you could add `wandb.init()` to the beginning of
    your training script as well as your evaluation script, and each piece would
    be tracked as a run in W&B.

    `wandb.init()` spawns a new background process to log data to a run, and it
    also syncs data to https://wandb.ai by default, so you can see your results
    in real-time.

    Call `wandb.init()` to start a run before logging data with `wandb.log()`.
    When you're done logging data, call `wandb.finish()` to end the run. If you
    don't call `wandb.finish()`, the run will end when your script exits.

    For more on using `wandb.init()`, including detailed examples, check out our
    [guide and FAQs](https://docs.wandb.ai/guides/track/launch).

    Examples:
        ### Explicitly set the entity and project and choose a name for the run:

        ```python
        import wandb

        run = wandb.init(
            entity="geoff",
            project="capsules",
            name="experiment-2021-10-31",
        )

        # ... your training code here ...

        run.finish()
        ```

        ### Add metadata about the run using the `config` argument:

        ```python
        import wandb

        config = {"lr": 0.01, "batch_size": 32}
        with wandb.init(config=config) as run:
            run.config.update({"architecture": "resnet", "depth": 34})

            # ... your training code here ...
        ```

        Note that you can use `wandb.init()` as a context manager to automatically
        call `wandb.finish()` at the end of the block.

    Args:
        entity: The username or team name under which the runs will be logged.
            The entity must already exist, so ensure you’ve created your account
            or team in the UI before starting to log runs. If not specified, the
            run will default your defualt entity. To change the default entity,
            go to [your settings](https://wandb.ai/settings) and update the
            "Default location to create new projects" under "Default team".
        project: The name of the project under which this run will be logged.
            If not specified, we use a heuristic to infer the project name based
            on the system, such as checking the git root or the current program
            file. If we can't infer the project name, the project will default to
            `"uncategorized"`.
        dir: An absolute path to the directory where metadata and downloaded
            files will be stored. When calling `download()` on an artifact, files
            will be saved to this directory. If not specified, this defaults to
            the `./wandb` directory.
        id: A unique identifier for this run, used for resuming. It must be unique
            within the project and cannot be reused once a run is deleted. The
            identifier must not contain any of the following special characters:
            `/ \ # ? % :`. For a short descriptive name, use the `name` field,
            or for saving hyperparameters to compare across runs, use `config`.
        name: A short display name for this run, which appears in the UI to help
            you identify it. By default, we generate a random two-word name
            allowing easy cross-reference runs from table to charts. Keeping these
            run names brief enhances readability in chart legends and tables. For
            saving hyperparameters, we recommend using the `config` field.
        notes: A detailed description of the run, similar to a commit message in
            Git. Use this argument to capture any context or details that may
            help you recall the purpose or setup of this run in the future.
        tags: A list of tags to label this run in the UI. Tags are helpful for
            organizing runs or adding temporary identifiers like "baseline" or
            "production." You can easily add, remove tags, or filter by tags in
            the UI.
            If resuming a run, the tags provided here will replace any existing
            tags. To add tags to a resumed run without overwriting the current
            tags, use `run.tags += ["new_tag"]` after calling `run = wandb.init()`.
        config: Sets `wandb.config`, a dictionary-like object for storing input
            parameters to your run, such as model hyperparameters or data
            preprocessing settings.
            The config appears in the UI in an overview page, allowing you to
            group, filter, and sort runs based on these parameters.
            Keys should not contain periods (`.`), and values should be
            smaller than 10 MB.
            If a dictionary, `argparse.Namespace`, or `absl.flags.FLAGS` is
            provided, the key-value pairs will be loaded directly into
            `wandb.config`.
            If a string is provided, it is interpreted as a path to a YAML file,
            from which configuration values will be loaded into `wandb.config`.
        config_exclude_keys: A list of specific keys to exclude from `wandb.config`.
        config_include_keys: A list of specific keys to include in `wandb.config`.
        allow_val_change: Controls whether config values can be modified after their
            initial set. By default, an exception is raised if a config value is
            overwritten. For tracking variables that change during training, such as
            a learning rate, consider using `wandb.log()` instead. By default, this
            is `False` in scripts and `True` in Notebook environments.
        group: Specify a group name to organize individual runs as part of a larger
            experiment. This is useful for cases like cross-validation or running
            multiple jobs that train and evaluate a model on different test sets.
            Grouping allows you to manage related runs collectively in the UI,
            making it easy to toggle and review results as a unified experiment.
            For more information, refer to our
            [guide to grouping runs](https://docs.wandb.com/guides/runs/grouping).
        job_type: Specify the type of run, especially helpful when organizing runs
            within a group as part of a larger experiment. For example, in a group,
            you might label runs with job types such as "train" and "eval".
            Defining job types enables you to easily filter and group similar runs
            in the UI, facilitating direct comparisons.
        mode: Specifies how run data is managed, with the following options:
            - `"online"` (default): Enables live syncing with W&B when a network
                connection is available, with real-time updates to visualizations.
            - `"offline"`: Suitable for air-gapped or offline environments; data
                is saved locally and can be synced later. Ensure the run folder
                is preserved to enable future syncing.
            - `"disabled"`: Disables all W&B functionality, making the run’s methods
                no-ops. Typically used in testing to bypass W&B operations.
        force: Determines if a W&B login is required to run the script. If `True`,
            the user must be logged in to W&B; otherwise, the script will not
            proceed. If `False` (default), the script can proceed without a login,
            switching to offline mode if the user is not logged in.
        anonymous: Specifies the level of control over anonymous data logging.
            Available options are:
            - `"never"` (default): Requires you to link your W&B account before
                tracking the run. This prevents unintentional creation of anonymous
                runs by ensuring each run is associated with an account.
            - `"allow"`: Enables a logged-in user to track runs with their account,
                but also allows someone running the script without a W&B account
                to view the charts and data in the UI.
            - `"must"`: Forces the run to be logged to an anonymous account, even
                if the user is logged in.
        reinit: Determines if multiple `wandb.init()` calls can start new runs
            within the same process. By default (`False`), if an active run
            exists, calling `wandb.init()` returns the existing run instead of
            creating a new one. When `reinit=True`, the active run is finished
            before a new run is initialized. In notebook environments, runs are
            reinitialized by default unless `reinit` is explicitly set to `False`.
        resume: Controls the behavior when resuming a run with the specified `id`.
            Available options are:
            - `"allow"`: If a run with the specified `id` exists, it will resume
                from the last step; otherwise, a new run will be created.
            - `"never"`: If a run with the specified `id` exists, an error will
                be raised. If no such run is found, a new run will be created.
            - `"must"`: If a run with the specified `id` exists, it will resume
                from the last step. If no run is found, an error will be raised.
            - `"auto"`: Automatically resumes the previous run if it crashed on
                this machine; otherwise, starts a new run.
            - `True`: Deprecated. Use `"auto"` instead.
            - `False`: Deprecated. Use the default behavior (leaving `resume`
                unset) to always start a new run.
            Note: If `resume` is set, `fork_from` and `resume_from` cannot be
            used. When `resume` is unset, the system will always start a new run.
            For more details, see our
            [guide to resuming runs](https://docs.wandb.com/guides/runs/resuming).
        resume_from: Specifies a moment in a previous run to resume a run from,
            using the format `{run_id}?_step={step}`. This allows users to truncate
            the history logged to a run at an intermediate step and resume logging
            from that step. The target run must be in the same project.
            If an `id` argument is also provided, the `resume_from` argument will
            take precedence.
            `resume`, `resume_from` and `fork_from` cannot be used together, only
            one of them can be used at a time.
            Note: This feature is in beta and may change in the future.
        fork_from: Specifies a point in a previous run from which to fork a new
            run, using the format `{id}?_step={step}`. This creates a new run that
            resumes logging from the specified step in the target run’s history.
            The target run must be part of the current project.
            If an `id` argument is also provided, it must be different from the
            `fork_from` argument, an error will be raised if they are the same.
            `resume`, `resume_from` and `fork_from` cannot be used together, only
            one of them can be used at a time.
            Note: This feature is in beta and may change in the future.
        save_code: Enables saving the main script or notebook to W&B, aiding in
            experiment reproducibility and allowing code comparisons across runs in
            the UI. By default, this is disabled, but you can change the default to
            enable on your [settings page](https://wandb.ai/settings).
        tensorboard: Deprecated. Use `sync_tensorboard` instead.
        sync_tensorboard: Enables automatic syncing of W&B logs from TensorBoard
            or TensorBoardX, saving relevant event files for viewing in the W&B UI.
            saving relevant event files for viewing in the W&B UI. (Default: `False`)
        monitor_gym: Enables automatic logging of videos of the environment when
            using OpenAI Gym. For additional details, see our
            [guide for gym integration](https://docs.wandb.com/guides/integrations/openai-gym).
        settings: Specifies a dictionary or `wandb.Settings` object with advanced
            settings for the run.

    Returns:
        A `Run` object, which is a handle to the current run. Use this object
        to perform operations like logging data, saving files, and finishing
        the run. See the [Run API](https://docs.wandb.ai/ref/python/run) for
        more details.

    Raises:
        Error: If some unknown or internal error happened during the run
            initialization.
        AuthenticationError: If the user failed to provide valid credentials.
        CommError: If there was a problem communicating with the W&B server.
        UsageError: If the user provided invalid arguments to the function.
        KeyboardInterrupt: If the user interrupts the run initialization process.
            If the user interrupts the run initialization process.
    """
    wandb._assert_is_user_process()  # type: ignore

    init_settings = Settings()
    if isinstance(settings, dict):
        init_settings = Settings(**settings)
    elif isinstance(settings, Settings):
        init_settings = settings

    # Explicit function arguments take precedence over settings
    if job_type is not None:
        init_settings.run_job_type = job_type
    if dir is not None:
        init_settings.root_dir = dir  # type: ignore
    if project is not None:
        init_settings.project = project
    if entity is not None:
        init_settings.entity = entity
    if reinit is not None:
        init_settings.reinit = reinit
    if tags is not None:
        init_settings.run_tags = tuple(tags)
    if group is not None:
        init_settings.run_group = group
    if name is not None:
        init_settings.run_name = name
    if notes is not None:
        init_settings.run_notes = notes
    if anonymous is not None:
        init_settings.anonymous = anonymous  # type: ignore
    if mode is not None:
        init_settings.mode = mode  # type: ignore
    if resume is not None:
        init_settings.resume = resume  # type: ignore
    if force is not None:
        init_settings.force = force
    # TODO: deprecate "tensorboard" in favor of "sync_tensorboard"
    if tensorboard is not None:
        init_settings.sync_tensorboard = tensorboard
    if sync_tensorboard is not None:
        init_settings.sync_tensorboard = sync_tensorboard
    if save_code is not None:
        init_settings.save_code = save_code
    if id is not None:
        init_settings.run_id = id
    if fork_from is not None:
        init_settings.fork_from = fork_from  # type: ignore
    if resume_from is not None:
        init_settings.resume_from = resume_from  # type: ignore

    try:
        wi = _WandbInit()
        wi.setup(
            init_settings=init_settings,
            config=config,
            config_exclude_keys=config_exclude_keys,
            config_include_keys=config_include_keys,
            allow_val_change=allow_val_change,
            monitor_gym=monitor_gym,
        )
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
        raise AssertionError()  # should never get here
