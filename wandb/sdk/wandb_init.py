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

    def __init__(self, wl: wandb_setup._WandbSetup) -> None:
        self._wl = wl

        self.kwargs = None
        self.sweep_config: dict[str, Any] = {}
        self.launch_config: dict[str, Any] = {}
        self.config: dict[str, Any] = {}
        self.run: Run | None = None
        self.backend: Backend | None = None

        self._teardown_hooks: list[TeardownHook] = []
        self.notebook: wandb.jupyter.Notebook | None = None  # type: ignore
        self.printer = printer.new_printer()

        self._init_telemetry_obj = telemetry.TelemetryRecord()

        self.deprecated_features_used: dict[str, str] = dict()

    @property
    def _logger(self) -> wandb_setup.Logger:
        return self._wl._get_logger()

    def warn_env_vars_change_after_setup(self) -> None:
        """Warn if environment variables change after wandb singleton is initialized.

        Any settings from environment variables set after the singleton is initialized
        (via login/setup/etc.) will be ignored.
        """
        singleton = wandb_setup.singleton()
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

    def clear_run_path_if_sweep_or_launch(
        self,
        init_settings: Settings,
    ) -> None:
        """Clear project/entity/run_id keys if in a Sweep or a Launch context.

        Args:
            init_settings: Settings specified in the call to `wandb.init()`.
        """
        when_doing_thing = ""

        if self._wl.settings.sweep_id:
            when_doing_thing = "when running a sweep"
        elif self._wl.settings.launch:
            when_doing_thing = "when running from a wandb launch context"

        if not when_doing_thing:
            return

        def warn(key: str, value: str) -> None:
            self.printer.display(
                f"Ignoring {key} {value!r} {when_doing_thing}.",
                level="warn",
            )

        if init_settings.project is not None:
            warn("project", init_settings.project)
            init_settings.project = None
        if init_settings.entity is not None:
            warn("entity", init_settings.entity)
            init_settings.entity = None
        if init_settings.run_id is not None:
            warn("run_id", init_settings.run_id)
            init_settings.run_id = None

    def login_and_compute_run_settings(
        self,
        init_settings: Settings,
    ) -> Settings:
        """Returns the run's settings after logging in if necessary.

        Args:
            init_settings: Settings passed to `wandb.init()` or set via explicit
                parameters.
        """
        self.warn_env_vars_change_after_setup()

        self.clear_run_path_if_sweep_or_launch(init_settings)

        # Inherit global settings.
        settings = self._wl.settings.model_copy()

        # Apply settings from wandb.init() call.
        settings.update_from_settings(init_settings)

        # Infer the run ID from SageMaker.
        if not settings.sagemaker_disable and sagemaker.is_using_sagemaker():
            if sagemaker.set_run_id(settings):
                self._logger.info("set run ID and group based on SageMaker")
                with telemetry.context(obj=self._init_telemetry_obj) as tel:
                    tel.feature.sagemaker = True

        if not settings._offline and not settings._noop:
            wandb_login._login(
                anonymous=settings.anonymous,
                force=settings.force,
                _disable_warning=True,
                _silent=settings.quiet or settings.silent,
                _entity=settings.entity,
            )

        # apply updated global state after login was handled
        login_settings = {
            k: v
            for k, v in {
                "anonymous": self._wl.settings.anonymous,
                "api_key": self._wl.settings.api_key,
                "base_url": self._wl.settings.base_url,
                "force": self._wl.settings.force,
                "login_timeout": self._wl.settings.login_timeout,
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
        # The reason this is not going through the settings object is to
        # avoid failure cases in other parts of the code that will be
        # removed with the switch to wandb-core.
        if settings.project is None:
            settings.project = wandb.util.auto_project_name(settings.program)

        settings.x_start_time = time.time()

        return settings

    def setup(
        self,
        settings: Settings,
        config: dict | str | None = None,
        config_exclude_keys: list[str] | None = None,
        config_include_keys: list[str] | None = None,
        monitor_gym: bool | None = None,
    ) -> None:
        """Compute the run's config and some telemetry."""
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

        # Construct the run's config.
        self.config = dict()
        self.init_artifact_config: dict[str, Any] = dict()

        if not settings.sagemaker_disable and sagemaker.is_using_sagemaker():
            sagemaker_config = sagemaker.parse_sm_config()
            self._split_artifacts_from_config(sagemaker_config, self.config)

            with telemetry.context(obj=self._init_telemetry_obj) as tel:
                tel.feature.sagemaker = True

        if self._wl._config:
            self._split_artifacts_from_config(self._wl._config, self.config)

        if config and isinstance(config, dict):
            self._split_artifacts_from_config(config, self.config)

        self.sweep_config = dict()
        sweep_config = self._wl._sweep_config or dict()
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

        if not settings._noop:
            self._log_setup(settings)

            if settings._jupyter:
                self._jupyter_setup(settings)
        launch_config = _handle_launch_config(settings)
        if launch_config:
            self._split_artifacts_from_config(launch_config, self.launch_config)

    def teardown(self) -> None:
        # TODO: currently this is only called on failed wandb.init attempts
        # normally this happens on the run object
        self._logger.info("tearing down wandb.init")
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

    def _create_logger(self, log_fname: str) -> logging.Logger:
        """Returns a logger configured to write to a file.

        This adds a run_id to the log, in case of multiple processes on the same
        machine. Currently, there is no way to disable logging after it's
        enabled.
        """
        handler = logging.FileHandler(log_fname)
        handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d "
            "[%(filename)s:%(funcName)s():%(lineno)s] %(message)s"
        )

        handler.setFormatter(formatter)

        logger = logging.getLogger("wandb")
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

        return logger

    def _safe_symlink(
        self, base: str, target: str, name: str, delete: bool = False
    ) -> None:
        # TODO(jhr): do this with relpaths, but i can't figure it out on no sleep
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
            self._logger.info("saved code: %s", res)  # type: ignore
        if self.backend.interface is not None:
            self._logger.info("pausing backend")  # type: ignore
            self.backend.interface.publish_pause()

    def _resume_backend(self, *args: Any, **kwargs: Any) -> None:  #  noqa
        if self.backend is not None and self.backend.interface is not None:
            self._logger.info("resuming backend")  # type: ignore
            self.backend.interface.publish_resume()

    def _jupyter_teardown(self) -> None:
        """Teardown hooks and display saving, called with wandb.finish."""
        assert self.notebook
        ipython = self.notebook.shell
        self.notebook.save_history()
        if self.notebook.save_ipynb():
            assert self.run is not None
            res = self.run.log_code(root=None)
            self._logger.info("saved code and history: %s", res)  # type: ignore
        self._logger.info("cleaning up jupyter logic")  # type: ignore
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
            self._logger.info("configuring jupyter hooks %s", self)  # type: ignore
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

        self._wl._early_logger_flush(self._create_logger(settings.log_user))
        self._logger.info(f"Logging user logs to {settings.log_user}")
        self._logger.info(f"Logging internal logs to {settings.log_internal}")

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
        # config, summary, and metadata objects
        drun._config = wandb.sdk.wandb_config.Config()
        drun._config.update(self.sweep_config)
        drun._config.update(self.config)
        drun.summary = SummaryDisabled()  # type: ignore
        drun._Run__metadata = wandb.sdk.wandb_metadata.Metadata()

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

    def init(self, settings: Settings) -> Run:  # noqa: C901
        self._logger.info("calling init triggers")
        trigger.call("on_init")

        assert self._wl is not None

        self._logger.info(
            f"wandb.init called with sweep_config: {self.sweep_config}\nconfig: {self.config}"
        )

        if settings._noop:
            return self._make_run_disabled()
        if (
            settings.reinit or (settings._jupyter and settings.reinit is not False)
        ) and len(self._wl._global_run_stack) > 0:
            if len(self._wl._global_run_stack) > 1:
                wandb.termwarn(
                    "Launching multiple wandb runs using Python's threading"
                    " module is not well-supported."
                    " Please use multiprocessing instead."
                    " Finishing previous run before initializing another."
                )

            latest_run = self._wl._global_run_stack[-1]
            self._logger.info(f"found existing run on stack: {latest_run.id}")
            latest_run.finish()
        elif wandb.run is not None and os.getpid() == wandb.run._init_pid:
            self._logger.info("wandb.init() called when a run is still active")
            with telemetry.context() as tel:
                tel.feature.init_return_run = True
            return wandb.run

        self._logger.info("starting backend")

        if not settings.x_disable_service:
            service = self._wl.ensure_service()
            self._logger.info("sending inform_init request")
            service.inform_init(
                settings=settings.to_proto(),
                run_id=settings.run_id,  # type: ignore
            )
        else:
            service = None

        mailbox = Mailbox()
        backend = Backend(
            settings=settings,
            service=service,
            mailbox=mailbox,
        )
        backend.ensure_launched()
        self._logger.info("backend started and connected")

        # resuming needs access to the server, check server_status()?
        run = Run(
            config=self.config,
            settings=settings,
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
            if settings._jupyter:
                tel.env.jupyter = True
            if settings._ipython:
                tel.env.ipython = True
            if settings._colab:
                tel.env.colab = True
            if settings._kaggle:
                tel.env.kaggle = True
            if settings._windows:
                tel.env.windows = True

            if settings.launch:
                tel.feature.launch = True

            for module_name in telemetry.list_telemetry_imports(only_imported=True):
                setattr(tel.imports_init, module_name, True)

            # probe the active start method
            active_start_method: str | None = None
            if settings.start_method == "thread":
                active_start_method = settings.start_method
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

            if settings._aws_lambda:
                tel.env.aws_lambda = True

            if os.environ.get(wandb.env._DISABLE_SERVICE):
                tel.feature.service_disabled = True

            if service:
                tel.feature.service = True
            if settings.x_flow_control_disabled:
                tel.feature.flow_control_disabled = True
            if settings.x_flow_control_custom:
                tel.feature.flow_control_custom = True
            if not settings.x_require_legacy_service:
                tel.feature.core = True
            if settings._shared:
                wandb.termwarn(
                    "The `_shared` feature is experimental and may change. "
                    "Please contact support@wandb.com for guidance and to report any issues."
                )
                tel.feature.shared_mode = True

            tel.env.maybe_mp = _maybe_mp_process(backend)

        if not settings.label_disable:
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

        self._logger.info("updated telemetry")

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
        if not (settings.disable_git or settings.x_disable_machine_info):
            run._populate_git_info()

        run_result: pb.RunUpdateResult | None = None

        if settings._offline:
            with telemetry.context(run=run) as tel:
                tel.feature.offline = True

            if settings.resume:
                wandb.termwarn(
                    "`resume` will be ignored since W&B syncing is set to `offline`. "
                    f"Starting a new run with run id {run.id}."
                )
        error: wandb.Error | None = None

        timeout = settings.init_timeout

        self._logger.info(
            f"communicating run to backend with {timeout} second timeout",
        )

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
            self._logger.error(f"encountered error: {error}")
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
            self._logger.info("run resumed")
            with telemetry.context(run=run) as tel:
                tel.feature.resumed = run_result.run.resumed
        run._set_run_obj(run_result.run)

        self._logger.info("starting run threads in backend")
        # initiate run (stats and metadata probing)

        if service:
            assert settings.run_id
            service.inform_start(
                settings=settings.to_proto(),
                run_id=settings.run_id,
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
            settings.launch
            and settings.launch_config_path
            and os.path.exists(settings.launch_config_path)
        ):
            run.save(settings.launch_config_path)
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
        self._logger.info("run started, returning control to user process")
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

    _wl = wandb.setup()
    logger = _wl._get_logger()

    service = _wl.ensure_service()

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
    in real-time. When you're done logging data, call `wandb.finish()` to end the run.
    If you don't call `wandb.finish()`, the run will end when your script exits.

    Call `wandb.init()` to start a run before logging data with `wandb.log()`:

    Args:
        project: The name of the project where you're sending
            the new run. If the project is not specified, we will try to infer
            the project name from git root or the current program file. If we
            can't infer the project name, we will default to `"uncategorized"`.
        entity: An entity is a username or team name where
            you're sending runs. This entity must exist before you can send runs
            there, so make sure to create your account or team in the UI before
            starting to log runs. If you don't specify an entity, the run is
            sent to your default entity.
        config: This sets `wandb.config`,
            a dictionary-like object for saving inputs
            to your job, like hyperparameters for a model or settings for a data
            preprocessing job. The config will show up in a table in the UI that
            you can use to group, filter, and sort runs. Keys should not contain
            `.` in their names, and values should be under 10 MB.
            If `dict`, argparse or `absl.flags` will load the key value pairs into
                the `wandb.config` object.
            If `str`, will look for a yaml file by that name, and load config from
                that file into the `wandb.config` object.
        save_code: Turn this on to save the main script or
            notebook to W&B. This is valuable for improving experiment
            reproducibility and to diff code across experiments in the UI. By
            default this is off, but you can flip the default behavior to on
            in your account's settings page.
        group: Specify a group to organize individual runs into
            a larger experiment. For example, you might be doing cross
            validation, or you might have multiple jobs that train and evaluate
            a model against different test sets. Group gives you a way to
            organize runs together into a larger whole, and you can toggle this
            on and off in the UI.
        job_type: Specify the type of run, which is useful when
            you're grouping runs together into larger experiments using group.
            For example, you might have multiple jobs in a group, with job types
            like train and eval. Setting this makes it easy to filter and group
            similar runs together in the UI so you can compare apples to apples.
        tags: A list of strings, which will populate the list
            of tags on this run in the UI. Tags are useful for organizing runs
            together, or applying temporary labels like "baseline" or
            "production". It's easy to add and remove tags in the UI, or filter
            down to just runs with a specific tag.
            If you are resuming a run, its tags will be overwritten by the tags
            you pass to `wandb.init()`. If you want to add tags to a resumed run
            without overwriting its existing tags, use `run.tags += ["new_tag"]`
            after `wandb.init()`.
        name: A short display name for this run, which is how
            you'll identify this run in the UI. By default, we generate a random
            two-word name that lets you easily cross-reference runs from the
            table to charts. Keeping these run names short makes the chart
            legends and tables easier to read. If you're looking for a place to
            save your hyperparameters, we recommend saving those in config.
        notes: A longer description of the run, like a `-m` commit
            message in git. This helps you remember what you were doing when you
            ran this run.
        dir: An absolute path to a directory where
            metadata will be stored. When you call `download()` on an artifact,
            this is the directory where downloaded files will be saved. By default,
            this is the `./wandb` directory.
        resume: Sets the resuming behavior. Options:
            `"allow"`, `"must"`, `"never"`, `"auto"` or `None`. Defaults to `None`.
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
        reinit: Allow multiple `wandb.init()` calls in the same
            process. Defaults to `False`.
        config_exclude_keys: string keys to exclude from
            `wandb.config`.
        config_include_keys: string keys to include in
            `wandb.config`.
        anonymous: Controls anonymous data logging.
        - `"never"` By default, you must link your W&B account before
            tracking the run, so you don't accidentally create an anonymous
            run.
        - `"allow"`: lets a logged-in user track runs with their account, but
            lets someone who is running the script without a W&B account see
            the charts in the UI.
        - `"must"`: sends the run to an anonymous account instead of to a
            signed-up user account.
        mode: Can be `"online"`, `"offline"` or `"disabled"`. Defaults to
            online.
        allow_val_change: Whether to allow config values to
            change after setting the keys once. By default, we throw an exception
            if a config value is overwritten. If you want to track something
            like a varying learning rate at multiple times during training, use
            `wandb.log()` instead. By default, set to `False` in scripts,
            `True` in Jupyter.
        force: If `True`, this crashes the script if a user isn't
            logged in to W&B. If `False`, this will let the script run in
            offline mode if a user isn't logged in to W&B. Default to `False`.
        sync_tensorboard: Synchronize wandb logs from tensorboard or
            tensorboardX and save the relevant events file. Defaults to `False`.
        tensorboard: Alias for `sync_tensorboard`, deprecated.
        monitor_gym: Automatically log videos of environment when
            using OpenAI Gym. Defaults to `False`.
        id: A unique ID for this run, used for resuming. It must
            be unique in the project, and if you delete a run you can't reuse
            the ID. Use the `name` field for a short descriptive name, or `config`
            for saving hyperparameters to compare across runs. The ID cannot
            contain the following special characters `/\#?%` or :.
        fork_from: A string with the format `{run_id}?_step={step}` describing
            a moment in a previous run to fork a new run from. Creates a new
            run that picks up logging history from the specified run at the
            specified moment. The target run must be in the current project.
        resume_from: A string with the format `{run_id}?_step={step}`
            describing a moment in a previous run to resume a run from.
            This allows users to truncate the history logged to a run at an
            intermediate step and resume logging from that step. It uses run
            forking under the hood. The target run must be in the current
            project.
        settings: Settings to use for this run. Defaults to `None`.

    Raises:
        Error: if some unknown or internal error happened during the run
            initialization.
        AuthenticationError: if the user failed to provide valid credentials.
        CommError: if there was a problem communicating with the WandB server.
        UsageError: if the user provided invalid arguments.
        KeyboardInterrupt: if user interrupts the run.

    Returns:
        A `Run` object.


    Examples:
    ```python
    import wandb

    wandb.init()
    # ... calculate metrics, generate media
    wandb.log({"accuracy": 0.9})
    ```

    `wandb.init()` returns a run object, and you can also access the run object
    with `wandb.run`:

    ```python
    import wandb

    run = wandb.init()

    assert run is wandb.run
    ```

    You can change where the run is logged, just like changing
    the organization, repository, and branch in git:

    ```python
    # Set where the run is logged
    import wandb

        config = {"lr": 0.01, "batch_size": 32}
        with wandb.init(config=config) as run:
            run.config.update({"architecture": "resnet", "depth": 34})

            # ... your training code here ...
    ```

    Pass a dictionary-style object as the `config` keyword argument to add
    metadata, like hyperparameters, to your run.

    ```python
    # Add metadata about the run to the config
    import wandb

    config = {"lr": 3e-4, "batch_size": 32}
    config.update({"architecture": "resnet", "depth": 34})
    wandb.init(config=config)
    ```
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

    wl: wandb_setup._WandbSetup | None = None

    try:
        wl = wandb.setup()

        wi = _WandbInit(wl)

        settings = wi.login_and_compute_run_settings(init_settings)

        wi.setup(
            settings=settings,
            config=config,
            config_exclude_keys=config_exclude_keys,
            config_include_keys=config_include_keys,
            monitor_gym=monitor_gym,
        )

        return wi.init(settings)

    except KeyboardInterrupt as e:
        if wl:
            wl._get_logger().warning("interrupted", exc_info=e)

        raise

    except Exception as e:
        if wl:
            wl._get_logger().exception("error in wandb.init()", exc_info=e)

        # Need to build delay into this sentry capture because our exit hooks
        # mess with sentry's ability to send out errors before the program ends.
        wandb._sentry.reraise(e)
        raise AssertionError()  # should never get here
