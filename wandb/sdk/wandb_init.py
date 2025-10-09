"""Defines wandb.init() and associated classes and methods.

`wandb.init()` indicates the beginning of a new run. In an ML training pipeline,
you could add `wandb.init()` to the beginning of your training script as well as
your evaluation script, and each step would be tracked as a run in W&B.

For more on using `wandb.init()`, including code snippets, check out our
[guide and FAQs](https://docs.wandb.ai/guides/track/launch).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import os
import pathlib
import platform
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Iterable, Iterator, Sequence

from typing_extensions import Any, Literal, Protocol, Self

import wandb
import wandb.env
from wandb import env, trigger
from wandb.errors import CommError, Error, UsageError
from wandb.errors.links import url_registry
from wandb.errors.util import ProtobufErrorHandler
from wandb.integration import sagemaker, weave
from wandb.proto.wandb_deprecated import Deprecated
from wandb.sdk.lib import ipython as wb_ipython
from wandb.sdk.lib import progress, runid, wb_logging
from wandb.sdk.lib.paths import StrPath
from wandb.util import _is_artifact_representation

from . import wandb_login, wandb_setup
from .backend.backend import Backend
from .lib import SummaryDisabled, filesystem, module, paths, printer, telemetry
from .lib.deprecate import deprecate
from .mailbox import wait_with_progress
from .wandb_helper import parse_config
from .wandb_run import Run, TeardownHook, TeardownStage
from .wandb_settings import Settings

if TYPE_CHECKING:
    import wandb.jupyter


def _huggingface_version() -> str | None:
    if "transformers" in sys.modules:
        trans = wandb.util.get_module("transformers")
        if hasattr(trans, "__version__"):
            return str(trans.__version__)
    return None


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


@dataclasses.dataclass(frozen=True)
class _ConfigParts:
    base_no_artifacts: dict[str, Any]
    """The run config passed to `init()` minus any artifact-valued keys."""

    sweep_no_artifacts: dict[str, Any]
    """The config loaded as part of a sweep minus any artifact-valued keys."""

    launch_no_artifacts: dict[str, Any]
    """The config loaded as part of Launch minus any artifact-valued keys."""

    artifacts: dict[str, Any]
    """Artifact keys removed from config dictionaries.

    Due to implementation details of how a Run is constructed,
    artifacts must be inserted into its config after initialization.
    """


class _PrinterCallback(Protocol):
    """A callback for displaying messages after a printer is configured.

    This is used for a few messages that may be generated before run settings
    are computed, which are necessary for creating a printer.
    """

    def __call__(self, run_printer: printer.Printer) -> None:
        """Display information through the given printer."""


def _noop_printer_callback() -> _PrinterCallback:
    """A printer callback that does not print anything."""
    return lambda _: None


def _concat_printer_callbacks(
    cbs: Iterable[_PrinterCallback],
) -> _PrinterCallback:
    """Returns a printer callback that runs the given callbacks in order."""

    def do_callbacks(run_printer: printer.Printer) -> None:
        for cb in cbs:
            cb(run_printer)

    return do_callbacks


class _WandbInit:
    def __init__(
        self,
        wl: wandb_setup._WandbSetup,
        telemetry: telemetry.TelemetryRecord,
    ) -> None:
        self._wl = wl

        self._telemetry = telemetry
        """Telemetry gathered before creating a run.

        After the run is created, `telemetry.context()` is used instead.
        """

        self.kwargs = None
        self.run: Run | None = None
        self.backend: Backend | None = None

        self._teardown_hooks: list[TeardownHook] = []
        self.notebook: wandb.jupyter.Notebook | None = None

        self.deprecated_features_used: dict[str, str] = dict()

    @property
    def _logger(self) -> wandb_setup.Logger:
        return self._wl._get_logger()

    def maybe_login(self, init_settings: Settings) -> None:
        """Log in if we are not creating an offline or disabled run.

        This may change the W&B singleton settings.

        Args:
            init_settings: Settings passed to `wandb.init()` or set via
                keyword arguments.
        """
        # Allow settings passed to init() to override inferred values.
        #
        # Calling login() may change settings on the singleton,
        # so these may not be the final run settings.
        run_settings = self._wl.settings.model_copy()
        run_settings.update_from_settings(init_settings)

        # NOTE: _noop or _offline can become true after _login().
        #   _noop happens if _login hits a timeout.
        #   _offline can be selected by the user at the login prompt.
        if run_settings._noop or run_settings._offline:
            return

        wandb_login._login(
            anonymous=run_settings.anonymous,
            host=run_settings.base_url,
            force=run_settings.force,
            _disable_warning=True,
            _silent=run_settings.quiet or run_settings.silent,
        )

    def warn_env_vars_change_after_setup(self) -> _PrinterCallback:
        """Warn if environment variables changed after `wandb.setup()`.

        Returns:
            A callback to print any generated warnings.
        """
        if not self._wl.did_environment_change():
            return _noop_printer_callback()

        def print_warning(run_printer: printer.Printer) -> None:
            line = (
                "Changes to your `wandb` environment variables will be ignored "
                "because your `wandb` session has already started. "
                "For more information on how to modify your settings with "
                "`wandb.init()` arguments, please refer to "
                f"{run_printer.link(url_registry.url('wandb-init'), 'the W&B docs')}."
            )
            run_printer.display(line, level="warn")

        return print_warning

    def clear_run_path_if_sweep_or_launch(
        self,
        init_settings: Settings,
    ) -> _PrinterCallback:
        """Clear project/entity/run_id keys if in a Sweep or a Launch context.

        Args:
            init_settings: Settings specified in the call to `wandb.init()`.

        Returns:
            A callback to print any generated warnings.
        """
        when_doing_thing = ""

        if self._wl.settings.sweep_id:
            when_doing_thing = "when running a sweep"
        elif self._wl.settings.launch:
            when_doing_thing = "when running from a wandb launch context"

        if not when_doing_thing:
            return _noop_printer_callback()

        warnings = []

        def warn(key: str, value: str) -> None:
            warnings.append(f"Ignoring {key} {value!r} {when_doing_thing}.")

        if init_settings.project is not None:
            warn("project", init_settings.project)
            init_settings.project = None
        if init_settings.entity is not None:
            warn("entity", init_settings.entity)
            init_settings.entity = None
        if init_settings.run_id is not None:
            warn("run_id", init_settings.run_id)
            init_settings.run_id = None

        def print_warnings(run_printer: printer.Printer) -> None:
            for warning in warnings:
                run_printer.display(warning, level="warn")

        return print_warnings

    def make_run_settings(
        self,
        init_settings: Settings,
    ) -> tuple[Settings, _PrinterCallback]:
        """Returns the run's settings and any warnings.

        Args:
            init_settings: Settings passed to `wandb.init()` or set via
                keyword arguments.
        """
        warning_callbacks: list[_PrinterCallback] = [
            self.warn_env_vars_change_after_setup(),
            self.clear_run_path_if_sweep_or_launch(init_settings),
        ]

        # Inherit global settings.
        settings = self._wl.settings.model_copy()

        # Apply settings from wandb.init() call.
        settings.update_from_settings(init_settings)

        # Infer the run ID from SageMaker.
        if not settings.sagemaker_disable and sagemaker.is_using_sagemaker():
            if sagemaker.set_run_id(settings):
                self._logger.info("set run ID and group based on SageMaker")
                self._telemetry.feature.sagemaker = True

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

        # In shared mode, generate a unique label if not provided.
        # The label is used to distinguish between system metrics and console logs
        # from different writers to the same run.
        if settings._shared and not settings.x_label:
            # TODO: If executed in a known distributed environment (e.g. Ray or SLURM),
            #   use the env vars to generate a label (e.g. SLURM_JOB_ID or RANK)
            prefix = settings.host or ""
            label = runid.generate_id()
            settings.x_label = f"{prefix}-{label}" if prefix else label

        return settings, _concat_printer_callbacks(warning_callbacks)

    def _load_autoresume_run_id(self, resume_file: pathlib.Path) -> str | None:
        """Returns the run_id stored in the auto-resume file, if any.

        Returns `None` if the file does not exist or is not in a valid format.

        Args:
            resume_file: The file path to use for resume='auto' mode.
        """
        if not resume_file.exists():
            return None

        with resume_file.open() as f:
            try:
                return json.load(f)["run_id"]

            except json.JSONDecodeError as e:
                self._logger.exception(
                    f"could not decode {resume_file}, ignoring",
                    exc_info=e,
                )
                return None

            except KeyError:
                self._logger.exception(
                    f"resume file at {resume_file} did not store a run_id"
                )
                return None

    def _save_autoresume_run_id(
        self,
        *,
        resume_file: pathlib.Path,
        run_id: str,
    ) -> None:
        """Write the run ID to the auto-resume file."""
        resume_file.parent.mkdir(exist_ok=True)
        with resume_file.open("w") as f:
            json.dump({"run_id": run_id}, f)

    def set_run_id(self, settings: Settings) -> None:
        """Set the run ID and possibly save it to the auto-resume file.

        After this, `settings.run_id` is guaranteed to be set.

        If a `resume_from` is provided and `run_id` is not set, initialize
        `run_id` with the `resume_from` run's `run_id`.

        Args:
            settings: The run's settings derived from the environment
                and explicit values passed to `wandb.init()`.
        """
        if settings.resume == "auto" and settings.resume_fname:
            resume_path = pathlib.Path(settings.resume_fname)
        else:
            resume_path = None

        if resume_path:
            previous_id = self._load_autoresume_run_id(resume_path)

            if not previous_id:
                pass
            elif settings.run_id is None:
                self._logger.info(f"loaded run ID from {resume_path}")
                settings.run_id = previous_id
            elif settings.run_id != previous_id:
                wandb.termwarn(
                    f"Ignoring ID {previous_id} loaded due to resume='auto'"
                    f" because the run ID is set to {settings.run_id}.",
                )

        # If no run ID was inferred, explicitly set, or loaded from an
        # auto-resume file, then we generate a new ID.
        if settings.run_id is None:
            # If resume_from is provided and run_id is not already set,
            # initialize run_id with the value from resume_from.
            if settings.resume_from:
                settings.run_id = settings.resume_from.run
            else:
                settings.run_id = runid.generate_id()

        if resume_path:
            self._save_autoresume_run_id(
                resume_file=resume_path,
                run_id=settings.run_id,
            )

    def set_sync_dir_suffix(self, settings: Settings) -> None:
        """Add a suffix to sync_dir if it already exists.

        The sync_dir uses a timestamp with second-level precision which can
        result in conflicts if a run with the same ID is initialized within the
        same second. This is most likely to happen in tests.

        This can't prevent conflicts from multiple processes attempting
        to create a wandb run simultaneously.

        Args:
            settings: Fully initialized settings other than the
                x_sync_dir_suffix setting which will be modified.
        """
        index = 1
        while pathlib.Path(settings.sync_dir).exists():
            settings.x_sync_dir_suffix = f"{index}"
            index += 1

    def make_run_config(
        self,
        settings: Settings,
        config: dict | str | None = None,
        config_exclude_keys: list[str] | None = None,
        config_include_keys: list[str] | None = None,
    ) -> _ConfigParts:
        """Construct the run's config.

        Args:
            settings: The run's finalized settings.
            config: The config passed to `init()`.
            config_exclude_keys: Deprecated. Keys to filter out from `config`.
            config_include_keys: Deprecated. Keys to include from `config`.

        Returns:
            Initial values for the run's config.
        """
        if config_exclude_keys:
            self.deprecated_features_used["init__config_exclude_keys"] = (
                "config_exclude_keys is deprecated. Use"
                " `config=wandb.helper.parse_config(config_object,"
                " exclude=('key',))` instead."
            )
        if config_include_keys:
            self.deprecated_features_used["init__config_include_keys"] = (
                "config_include_keys is deprecated. Use"
                " `config=wandb.helper.parse_config(config_object,"
                " include=('key',))` instead."
            )
        config = parse_config(
            config or dict(),
            include=config_include_keys,
            exclude=config_exclude_keys,
        )

        result = _ConfigParts(
            base_no_artifacts=dict(),
            sweep_no_artifacts=dict(),
            launch_no_artifacts=dict(),
            artifacts=dict(),
        )

        if not settings.sagemaker_disable and sagemaker.is_using_sagemaker():
            sagemaker_config = sagemaker.parse_sm_config()
            self._split_artifacts_from_config(
                sagemaker_config,
                config_target=result.base_no_artifacts,
                artifacts=result.artifacts,
            )
            self._telemetry.feature.sagemaker = True

        if self._wl.config:
            self._split_artifacts_from_config(
                self._wl.config,
                config_target=result.base_no_artifacts,
                artifacts=result.artifacts,
            )

        if config and isinstance(config, dict):
            self._split_artifacts_from_config(
                config,
                config_target=result.base_no_artifacts,
                artifacts=result.artifacts,
            )

        if self._wl._sweep_config:
            self._split_artifacts_from_config(
                self._wl._sweep_config,
                config_target=result.sweep_no_artifacts,
                artifacts=result.artifacts,
            )

        if launch_config := _handle_launch_config(settings):
            self._split_artifacts_from_config(
                launch_config,
                config_target=result.launch_no_artifacts,
                artifacts=result.artifacts,
            )

        wandb_internal = result.base_no_artifacts.setdefault("_wandb", dict())

        if settings.save_code and settings.program_relpath:
            wandb_internal["code_path"] = paths.LogicalPath(
                os.path.join("code", settings.program_relpath)
            )
        if settings.fork_from is not None:
            wandb_internal["branch_point"] = {
                "run_id": settings.fork_from.run,
                "step": settings.fork_from.value,
            }
        if settings.resume_from is not None:
            wandb_internal["branch_point"] = {
                "run_id": settings.resume_from.run,
                "step": settings.resume_from.value,
            }

        return result

    def teardown(self) -> None:
        # TODO: currently this is only called on failed wandb.init attempts
        # normally this happens on the run object
        self._logger.info("tearing down wandb.init")
        for hook in self._teardown_hooks:
            hook.call()

    def _split_artifacts_from_config(
        self,
        config_source: dict,
        config_target: dict,
        artifacts: dict,
    ) -> None:
        for k, v in config_source.items():
            if _is_artifact_representation(v):
                artifacts[k] = v
            else:
                config_target.setdefault(k, v)

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

    def _pre_run_cell_hook(self, *args, **kwargs) -> None:
        """Hook for the IPython pre_run_cell event.

        This pauses a run, preventing system metrics from being collected
        the run's runtime from increasing. It also uploads the notebook's code.
        """
        if not self.backend:
            return

        if self.notebook and self.notebook.save_ipynb():
            assert self.run is not None
            res = self.run.log_code(root=None)
            self._logger.info("saved code: %s", res)

        if self.backend.interface is not None:
            self._logger.info("pausing backend")
            self.backend.interface.publish_pause()

    def _post_run_cell_hook(self, *args, **kwargs) -> None:
        """Hook for the IPython post_run_cell event.

        Resumes collection of system metrics and the run's timer.
        """
        if self.backend is None or self.backend.interface is None:
            return

        self._logger.info("resuming backend")
        self.backend.interface.publish_resume()

    def _jupyter_teardown(self) -> None:
        """Teardown hooks and display saving, called with wandb.finish."""
        assert self.notebook
        ipython = self.notebook.shell

        if self.run:
            self.notebook.save_history(self.run)

        if self.notebook.save_ipynb():
            assert self.run is not None
            res = self.run.log_code(root=None)
            self._logger.info("saved code and history: %s", res)
        self._logger.info("cleaning up jupyter logic")

        ipython.events.unregister("pre_run_cell", self._pre_run_cell_hook)
        ipython.events.unregister("post_run_cell", self._post_run_cell_hook)

        ipython.display_pub.publish = ipython.display_pub._orig_publish
        del ipython.display_pub._orig_publish

    def monkeypatch_ipython(self, settings: Settings) -> None:
        """Add hooks, and session history saving."""
        self.notebook = wandb.jupyter.Notebook(settings)
        ipython = self.notebook.shell

        # Monkey patch ipython publish to capture displayed outputs
        if not hasattr(ipython.display_pub, "_orig_publish"):
            self._logger.info("configuring jupyter hooks %s", self)
            ipython.display_pub._orig_publish = ipython.display_pub.publish

            ipython.events.register("pre_run_cell", self._pre_run_cell_hook)
            ipython.events.register("post_run_cell", self._post_run_cell_hook)

            self._teardown_hooks.append(
                TeardownHook(self._jupyter_teardown, TeardownStage.EARLY)
            )

        def publish(data, metadata=None, **kwargs) -> None:
            ipython.display_pub._orig_publish(data, metadata=metadata, **kwargs)
            assert self.notebook is not None
            self.notebook.save_display(
                ipython.execution_count, {"data": data, "metadata": metadata}
            )

        ipython.display_pub.publish = publish

    @contextlib.contextmanager
    def setup_run_log_directory(self, settings: Settings) -> Iterator[None]:
        """Set up the run's log directory.

        This is a context manager that closes and unregisters the log handler
        in case of an uncaught exception, so that future logged messages do not
        modify this run's log file.
        """
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

        assert settings.run_id
        handler = wb_logging.add_file_handler(
            settings.run_id,
            pathlib.Path(settings.log_user),
        )

        if env.is_debug():
            handler.setLevel(logging.DEBUG)

        disposed = False

        def dispose_handler() -> None:
            nonlocal disposed

            if not disposed:
                disposed = True
                logging.getLogger("wandb").removeHandler(handler)
                handler.close()

        try:
            self._teardown_hooks.append(
                TeardownHook(
                    call=dispose_handler,
                    stage=TeardownStage.LATE,
                )
            )

            self._wl._early_logger_flush(logging.getLogger("wandb"))
            self._logger.info(f"Logging user logs to {settings.log_user}")
            self._logger.info(f"Logging internal logs to {settings.log_internal}")

            yield
        except Exception:
            dispose_handler()
            raise

    def make_disabled_run(self, config: _ConfigParts) -> Run:
        """Returns a Run-like object where all methods are no-ops.

        This method is used when the `mode` setting is set to "disabled", such as
        by wandb.init(mode="disabled") or by setting the WANDB_MODE environment
        variable to "disabled".

        It creates a Run object that mimics the behavior of a normal Run but doesn't
        communicate with the W&B servers.

        The returned Run object has all expected attributes and methods, but they
        are no-op versions that don't perform any actual logging or communication.
        """
        run_id = runid.generate_id()
        drun = Run(
            settings=Settings(
                mode="disabled",
                root_dir=tempfile.gettempdir(),
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
        drun._config.update(config.sweep_no_artifacts)
        drun._config.update(config.base_no_artifacts)
        drun.summary = SummaryDisabled()  # type: ignore

        # methods
        drun.log = lambda data, *_, **__: drun.summary.update(data)  # type: ignore[method-assign]
        drun.finish = lambda *_, **__: module.unset_globals()  # type: ignore[method-assign]
        drun.join = drun.finish  # type: ignore[method-assign]
        drun.define_metric = lambda *_, **__: wandb.sdk.wandb_metric.Metric("dummy")  # type: ignore[method-assign]
        drun.save = lambda *_, **__: False  # type: ignore[method-assign]
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

        # set properties to None
        for attr in ("url", "project_url", "sweep_url"):
            setattr(type(drun), attr, property(lambda _: None))

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

        drun.log_artifact = _ChainableNoOpField()  # type: ignore
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

    def init(  # noqa: C901
        self,
        settings: Settings,
        config: _ConfigParts,
        run_printer: printer.Printer,
    ) -> Run:
        self._logger.info("calling init triggers")
        trigger.call("on_init")

        assert self._wl is not None

        self._logger.info(
            f"wandb.init called with sweep_config: {config.sweep_no_artifacts}"
            f"\nconfig: {config.base_no_artifacts}"
        )

        if previous_run := self._wl.most_recent_active_run:
            if (
                settings.reinit in (True, "finish_previous")
                # calling wandb.init() in notebooks finishes previous runs
                # by default for user convenience.
                or (settings.reinit == "default" and wb_ipython.in_notebook())
            ):
                run_printer.display(
                    "Finishing previous runs because reinit is set"
                    f" to {settings.reinit!r}."
                )
                self._wl.finish_all_active_runs()

            elif settings.reinit == "create_new":
                self._logger.info(
                    "wandb.init() called while a run is active,"
                    " and reinit is set to 'create_new', so continuing"
                )

            elif settings.resume == "must":
                raise wandb.Error(
                    "Cannot resume a run while another run is active."
                    " You must either finish it using run.finish(),"
                    " or use reinit='create_new' when calling wandb.init()."
                )

            else:
                run_printer.display(
                    "wandb.init() called while a run is active and reinit is"
                    f" set to {settings.reinit!r}, so returning the previous"
                    " run."
                )

                with telemetry.context(run=previous_run) as tel:
                    tel.feature.init_return_run = True

                return previous_run

        self._logger.info("starting backend")

        service = self._wl.ensure_service()
        self._logger.info("sending inform_init request")
        service.inform_init(
            settings=settings.to_proto(),
            run_id=settings.run_id,  # type: ignore
        )

        backend = Backend(settings=settings, service=service)
        backend.ensure_launched()
        self._logger.info("backend started and connected")

        run = Run(
            config=config.base_no_artifacts,
            settings=settings,
            sweep_config=config.sweep_no_artifacts,
            launch_config=config.launch_no_artifacts,
        )

        # Populate initial telemetry
        with telemetry.context(run=run, obj=self._telemetry) as tel:
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

            if os.environ.get("PEX"):
                tel.env.pex = True

            if settings._aws_lambda:
                tel.env.aws_lambda = True

            if settings.x_flow_control_disabled:
                tel.feature.flow_control_disabled = True
            if settings.x_flow_control_custom:
                tel.feature.flow_control_custom = True
            if settings._shared:
                wandb.termwarn(
                    "The `shared` mode feature is experimental and may change. "
                    "Please contact support@wandb.com for guidance and to report any issues."
                )
                tel.feature.shared_mode = True

            if settings.x_label:
                tel.feature.user_provided_label = True

            if wandb.env.dcgm_profiling_enabled():
                tel.feature.dcgm_profiling_enabled = True

        if not settings.label_disable:
            if self.notebook:
                run._label_probe_notebook(self.notebook)
            else:
                run._label_probe_main()

        for deprecated_feature, msg in self.deprecated_features_used.items():
            deprecate(
                field_name=getattr(Deprecated, deprecated_feature),
                warning_message=msg,
                run=run,
            )

        self._logger.info("updated telemetry")

        run._set_library(self._wl)
        run._set_backend(backend)
        run._set_teardown_hooks(self._teardown_hooks)

        assert backend.interface
        backend.interface.publish_header()

        # Using GitRepo() blocks & can be slow, depending on user's current git setup.
        # We don't want to block run initialization/start request, so populate run's git
        # info beforehand.
        if not (settings.disable_git or settings.x_disable_machine_info):
            run._populate_git_info()

        if settings._offline and settings.resume:
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

        async def display_init_message() -> None:
            assert backend.interface

            with progress.progress_printer(
                run_printer,
                default_text="Waiting for wandb.init()...",
            ) as progress_printer:
                await progress.loop_printing_operation_stats(
                    progress_printer,
                    backend.interface,
                )

        try:
            result = wait_with_progress(
                run_init_handle,
                timeout=timeout,
                display_progress=display_init_message,
            )

        except TimeoutError:
            run_init_handle.cancel(backend.interface)

            # This may either be an issue with the W&B server (a CommError)
            # or a bug in the SDK (an Error). We cannot distinguish between
            # the two causes here.
            raise CommError(
                f"Run initialization has timed out after {timeout} sec."
                " Please try increasing the timeout with the `init_timeout`"
                " setting: `wandb.init(settings=wandb.Settings(init_timeout=120))`."
            )

        assert result.run_result

        if error := ProtobufErrorHandler.to_exception(result.run_result.error):
            raise error

        if not result.run_result.HasField("run"):
            raise Error("Assertion failed: run_result is missing the run field")

        if result.run_result.run.resumed:
            self._logger.info("run resumed")
            with telemetry.context(run=run) as tel:
                tel.feature.resumed = result.run_result.run.resumed
        run._set_run_obj(result.run_result.run)

        self._logger.info("starting run threads in backend")

        assert backend.interface

        run_start_handle = backend.interface.deliver_run_start(run)
        try:
            # TODO: add progress to let user know we are doing something
            run_start_handle.wait_or(timeout=30)
        except TimeoutError:
            pass

        backend.interface.publish_probe_system_info()

        assert self._wl is not None
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
        for k, v in config.artifacts.items():
            run.config.update({k: v}, allow_val_change=True)
        job_artifact = run._launch_artifact_mapping.get(
            wandb.util.LAUNCH_JOB_ARTIFACT_SLOT_NAME
        )
        if job_artifact:
            run.use_artifact(job_artifact)

        self.backend = backend

        if settings.reinit != "create_new":
            _set_global_run(run)

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

    _wl = wandb_setup.singleton()
    logger = _wl._get_logger()

    service = _wl.ensure_service()

    try:
        attach_settings = service.inform_attach(attach_id=attach_id)
    except Exception as e:
        raise UsageError(f"Unable to attach to run {attach_id}") from e

    settings = _wl.settings.model_copy()
    settings.update_from_dict(
        {
            "run_id": attach_id,
            "x_start_time": attach_settings.x_start_time.value,
            "mode": attach_settings.mode.value,
        }
    )

    # TODO: consolidate this codepath with wandb.init()
    backend = Backend(settings=settings, service=service)
    backend.ensure_launched()
    logger.info("attach backend started and connected")

    if run is None:
        run = Run(settings=settings)
    else:
        run._init(settings=settings)
    run._set_library(_wl)
    run._set_backend(backend)
    assert backend.interface

    attach_handle = backend.interface.deliver_attach(attach_id)
    try:
        # TODO: add progress to let user know we are doing something
        attach_result = attach_handle.wait_or(timeout=30)
    except TimeoutError:
        raise UsageError("Timeout attaching to run")

    attach_response = attach_result.response.attach_response
    if attach_response.error and attach_response.error.message:
        raise UsageError(f"Failed to attach to run: {attach_response.error.message}")

    run._set_run_obj(attach_response.run)
    _set_global_run(run)
    run._on_attach()
    return run


def _set_global_run(run: Run) -> None:
    """Set `wandb.run` and point some top-level functions to its methods.

    Args:
        run: The run to make global.
    """
    module.set_global(
        run=run,
        config=run.config,
        log=run.log,
        summary=run.summary,
        save=run.save,
        use_artifact=run.use_artifact,
        log_artifact=run.log_artifact,
        define_metric=run.define_metric,
        alert=run.alert,
        watch=run.watch,
        unwatch=run.unwatch,
        mark_preempting=run.mark_preempting,
        log_model=run.log_model,
        use_model=run.use_model,
        link_model=run.link_model,
    )


def _monkeypatch_openai_gym() -> None:
    """Patch OpenAI gym to log to the global `wandb.run`."""
    if len(wandb.patched["gym"]) > 0:
        return

    from wandb.integration import gym

    gym.monitor()


def _monkeypatch_tensorboard() -> None:
    """Patch TensorBoard to log to the global `wandb.run`."""
    if len(wandb.patched["tensorboard"]) > 0:
        return

    from wandb.integration import tensorboard as tb_module

    tb_module.patch()


def try_create_root_dir(settings: Settings) -> None:
    """Try to create the root directory specified in settings.

    If creation fails due to permissions or other errors,
    falls back to using the system temp directory.

    Args:
        settings: The runs settings containing root_dir configuration.
            This function may update the root_dir to a temporary directory
            if the parent directory is not writable.
    """
    fallback_to_temp_dir = False

    try:
        os.makedirs(settings.root_dir, exist_ok=True)
    except OSError:
        wandb.termwarn(
            f"Unable to create root directory {settings.root_dir}",
            repeat=False,
        )
        fallback_to_temp_dir = True
    else:
        if not os.access(settings.root_dir, os.W_OK | os.R_OK):
            wandb.termwarn(
                f"Path {settings.root_dir} wasn't read/writable",
                repeat=False,
            )
            fallback_to_temp_dir = True

    if not fallback_to_temp_dir:
        return

    tmp_dir = tempfile.gettempdir()
    if not os.access(tmp_dir, os.W_OK | os.R_OK):
        raise ValueError(
            f"System temp directory ({tmp_dir}) is not writable/readable, "
            "please set the `dir` argument in `wandb.init()` to a writable/readable directory."
        )

    settings.root_dir = tmp_dir
    wandb.termwarn(
        f"Falling back to temporary directory {tmp_dir}.",
        repeat=False,
    )
    os.makedirs(settings.root_dir, exist_ok=True)


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
    mode: Literal["online", "offline", "disabled", "shared"] | None = None,
    force: bool | None = None,
    anonymous: Literal["never", "allow", "must"] | None = None,
    reinit: (
        bool
        | Literal[
            None,
            "default",
            "return_previous",
            "finish_previous",
            "create_new",
        ]
    ) = None,
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
    in real-time. When you're done logging data, call `wandb.Run.finish()` to end the run.
    If you don't call `run.finish()`, the run will end when your script exits.

    Run IDs must not contain any of the following special characters `/ \ # ? % :`

    Args:
        entity: The username or team name the runs are logged to.
            The entity must already exist, so ensure you create your account
            or team in the UI before starting to log runs. If not specified, the
            run will default your default entity. To change the default entity,
            go to your settings and update the
            "Default location to create new projects" under "Default team".
        project: The name of the project under which this run will be logged.
            If not specified, we use a heuristic to infer the project name based
            on the system, such as checking the git root or the current program
            file. If we can't infer the project name, the project will default to
            `"uncategorized"`.
        dir: The absolute path to the directory where experiment logs and
            metadata files are stored. If not specified, this defaults
            to the `./wandb` directory. Note that this does not affect the
            location where artifacts are stored when calling `download()`.
        id: A unique identifier for this run, used for resuming. It must be unique
            within the project and cannot be reused once a run is deleted. For
            a short descriptive name, use the `name` field,
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
            tags, use `run.tags += ("new_tag",)` after calling `run = wandb.init()`.
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
        - `"shared"`: (This is an experimental feature). Allows multiple processes,
            possibly on different machines, to simultaneously log to the same run.
            In this approach you use a primary node and one or more worker nodes
            to log data to the same run. Within the primary node you
            initialize a run. For each worker node, initialize a run
            using the run ID used by the primary node.
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
        reinit: Shorthand for the "reinit" setting. Determines the behavior of
            `wandb.init()` when a run is active.
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
            If `resume` is set, `fork_from` and `resume_from` cannot be
            used. When `resume` is unset, the system will always start a new run.
        resume_from: Specifies a moment in a previous run to resume a run from,
            using the format `{run_id}?_step={step}`. This allows users to truncate
            the history logged to a run at an intermediate step and resume logging
            from that step. The target run must be in the same project.
            If an `id` argument is also provided, the `resume_from` argument will
            take precedence.
            `resume`, `resume_from` and `fork_from` cannot be used together, only
            one of them can be used at a time.
            Note that this feature is in beta and may change in the future.
        fork_from: Specifies a point in a previous run from which to fork a new
            run, using the format `{id}?_step={step}`. This creates a new run that
            resumes logging from the specified step in the target run’s history.
            The target run must be part of the current project.
            If an `id` argument is also provided, it must be different from the
            `fork_from` argument, an error will be raised if they are the same.
            `resume`, `resume_from` and `fork_from` cannot be used together, only
            one of them can be used at a time.
            Note that this feature is in beta and may change in the future.
        save_code: Enables saving the main script or notebook to W&B, aiding in
            experiment reproducibility and allowing code comparisons across runs in
            the UI. By default, this is disabled, but you can change the default to
            enable on your settings page.
        tensorboard: Deprecated. Use `sync_tensorboard` instead.
        sync_tensorboard: Enables automatic syncing of W&B logs from TensorBoard
            or TensorBoardX, saving relevant event files for viewing in
            the W&B UI.
        monitor_gym: Enables automatic logging of videos of the environment when
            using OpenAI Gym.
        settings: Specifies a dictionary or `wandb.Settings` object with advanced
            settings for the run.

    Returns:
        A `Run` object.

    Raises:
        Error: If some unknown or internal error happened during the run
            initialization.
        AuthenticationError: If the user failed to provide valid credentials.
        CommError: If there was a problem communicating with the WandB server.
        UsageError: If the user provided invalid arguments.
        KeyboardInterrupt: If user interrupts the run.

    Examples:
    `wandb.init()` returns a `Run` object. Use the run object to log data,
    save artifacts, and manage the run lifecycle.

    ```python
    import wandb

    config = {"lr": 0.01, "batch_size": 32}
    with wandb.init(config=config) as run:
        # Log accuracy and loss to the run
        acc = 0.95  # Example accuracy
        loss = 0.05  # Example loss
        run.log({"accuracy": acc, "loss": loss})
    ```
    """
    wandb._assert_is_user_process()  # type: ignore

    init_telemetry = telemetry.TelemetryRecord()

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

    if config is not None:
        init_telemetry.feature.set_init_config = True

    wl: wandb_setup._WandbSetup | None = None

    try:
        wl = wandb_setup.singleton()

        wi = _WandbInit(wl, init_telemetry)

        wi.maybe_login(init_settings)
        run_settings, show_warnings = wi.make_run_settings(init_settings)

        if isinstance(run_settings.reinit, bool):
            wi.deprecated_features_used["run__reinit_bool"] = (
                "Using a boolean value for 'reinit' is deprecated."
                " Use 'return_previous' or 'finish_previous' instead."
            )

        if run_settings.run_id is not None:
            init_telemetry.feature.set_init_id = True
        if run_settings.run_name is not None:
            init_telemetry.feature.set_init_name = True
        if run_settings.run_tags is not None:
            init_telemetry.feature.set_init_tags = True
        if run_settings._offline:
            init_telemetry.feature.offline = True
        if run_settings.fork_from is not None:
            init_telemetry.feature.fork_mode = True
        if run_settings.resume_from is not None:
            init_telemetry.feature.rewind_mode = True

        wi.set_run_id(run_settings)
        wi.set_sync_dir_suffix(run_settings)
        run_printer = printer.new_printer(run_settings)
        show_warnings(run_printer)

        with contextlib.ExitStack() as exit_stack:
            exit_stack.enter_context(wb_logging.log_to_run(run_settings.run_id))

            run_config = wi.make_run_config(
                settings=run_settings,
                config=config,
                config_exclude_keys=config_exclude_keys,
                config_include_keys=config_include_keys,
            )

            if run_settings._noop:
                return wi.make_disabled_run(run_config)

            try_create_root_dir(run_settings)
            exit_stack.enter_context(wi.setup_run_log_directory(run_settings))

            if run_settings._jupyter:
                wi.monkeypatch_ipython(run_settings)

            if monitor_gym:
                _monkeypatch_openai_gym()

            if wandb.patched["tensorboard"]:
                # NOTE: The user may have called the patch function directly.
                init_telemetry.feature.tensorboard_patch = True
            if run_settings.sync_tensorboard:
                _monkeypatch_tensorboard()
                init_telemetry.feature.tensorboard_sync = True

            if run_settings.x_server_side_derived_summary:
                init_telemetry.feature.server_side_derived_summary = True

            run = wi.init(run_settings, run_config, run_printer)

            # Set up automatic Weave integration if Weave is installed
            weave.setup(run_settings.entity, run_settings.project)

            return run

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
