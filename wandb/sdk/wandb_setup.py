#
"""Setup wandb session.

This module configures a wandb session which can extend to multiple wandb runs.

Functions:
    setup(): Configure wandb session.

Early logging keeps track of logger output until the call to wandb.init() when the
run_id can be resolved.

"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import TYPE_CHECKING, Any, Union

import wandb
import wandb.integration.sagemaker as sagemaker
from wandb.sdk.lib import import_hooks, wb_logging

from . import wandb_settings
from .lib import config_util, server

if TYPE_CHECKING:
    from wandb.sdk.lib.service_connection import ServiceConnection
    from wandb.sdk.wandb_settings import Settings


class _EarlyLogger:
    """Early logger which captures logs in memory until logging can be configured."""

    def __init__(self) -> None:
        self._log: list[tuple] = []
        self._exception: list[tuple] = []
        # support old warn() as alias of warning()
        self.warn = self.warning

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log.append((logging.DEBUG, msg, args, kwargs))

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log.append((logging.INFO, msg, args, kwargs))

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log.append((logging.WARNING, msg, args, kwargs))

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log.append((logging.ERROR, msg, args, kwargs))

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log.append((logging.CRITICAL, msg, args, kwargs))

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._exception.append((msg, args, kwargs))

    def log(self, level: str, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log.append((level, msg, args, kwargs))

    def _flush(self, new_logger: Logger) -> None:
        assert self is not new_logger
        for level, msg, args, kwargs in self._log:
            new_logger.log(level, msg, *args, **kwargs)
        for msg, args, kwargs in self._exception:
            new_logger.exception(msg, *args, **kwargs)


Logger = Union[logging.Logger, _EarlyLogger]


class _WandbSetup:
    """W&B library singleton."""

    def __init__(
        self,
        pid: int,
        settings: Settings | None = None,
        environ: dict | None = None,
    ) -> None:
        self._connection: ServiceConnection | None = None

        self._environ = environ or dict(os.environ)
        self._sweep_config: dict | None = None
        self._config: dict | None = None
        self._server: server.Server | None = None
        self._pid = pid

        # TODO(jhr): defer strict checks until settings are fully initialized
        #            and logging is ready
        self._logger: Logger = _EarlyLogger()

        self._settings = self._settings_setup(settings)

        wandb.termsetup(self._settings, None)

        self._check()
        self._setup()

    def _settings_setup(
        self,
        settings: Settings | None,
    ) -> wandb_settings.Settings:
        s = wandb_settings.Settings()

        # the pid of the process to monitor for system stats
        pid = os.getpid()
        self._logger.info(f"Current SDK version is {wandb.__version__}")
        self._logger.info(f"Configure stats pid to {pid}")
        s.x_stats_pid = pid

        # load settings from the system config
        if s.settings_system:
            self._logger.info(f"Loading settings from {s.settings_system}")
        s.update_from_system_config_file()

        # load settings from the workspace config
        if s.settings_workspace:
            self._logger.info(f"Loading settings from {s.settings_workspace}")
        s.update_from_workspace_config_file()

        # load settings from the environment variables
        self._logger.info("Loading settings from environment variables")
        s.update_from_env_vars(self._environ)

        # infer settings from the system environment
        s.update_from_system_environment()

        # load SageMaker settings
        check_sagemaker_env = not s.sagemaker_disable
        if settings and settings.sagemaker_disable:
            check_sagemaker_env = False
        if check_sagemaker_env and sagemaker.is_using_sagemaker():
            self._logger.info("Loading SageMaker settings")
            sagemaker.set_global_settings(s)

        # load settings from the passed init/setup settings
        if settings:
            s.update_from_settings(settings)

        return s

    def _update(self, settings: Settings | None = None) -> None:
        if not settings:
            return
        self._settings.update_from_settings(settings)

    def _update_user_settings(self) -> None:
        # Get rid of cached results to force a refresh.
        self._server = None
        user_settings = self._load_user_settings()
        if user_settings is not None:
            self._settings.update_from_dict(user_settings)

    def _early_logger_flush(self, new_logger: Logger) -> None:
        if self._logger is new_logger:
            return

        if isinstance(self._logger, _EarlyLogger):
            self._logger._flush(new_logger)
        self._logger = new_logger

    def _get_logger(self) -> Logger:
        return self._logger

    @property
    def settings(self) -> wandb_settings.Settings:
        return self._settings

    def _get_entity(self) -> str | None:
        if self._settings and self._settings._offline:
            return None
        entity = self.viewer.get("entity")
        return entity

    def _get_username(self) -> str | None:
        if self._settings and self._settings._offline:
            return None
        return self.viewer.get("username")

    def _get_teams(self) -> list[str]:
        if self._settings and self._settings._offline:
            return []
        teams = self.viewer.get("teams")
        if teams:
            teams = [team["node"]["name"] for team in teams["edges"]]
        return teams or []

    @property
    def viewer(self) -> dict[str, Any]:
        if self._server is None:
            self._server = server.Server(settings=self._settings)

        return self._server.viewer

    def _load_user_settings(self) -> dict[str, Any] | None:
        # offline?
        if self._server is None:
            return None

        flags = self._server._flags
        user_settings = dict()
        if "code_saving_enabled" in flags:
            user_settings["save_code"] = flags["code_saving_enabled"]

        email = self.viewer.get("email", None)
        if email:
            user_settings["email"] = email

        return user_settings

    def _check(self) -> None:
        if hasattr(threading, "main_thread"):
            if threading.current_thread() is not threading.main_thread():
                pass
        elif threading.current_thread().name != "MainThread":
            wandb.termwarn(f"bad thread2: {threading.current_thread().name}")
        if getattr(sys, "frozen", False):
            wandb.termwarn("frozen, could be trouble")

    def _setup(self) -> None:
        sweep_path = self._settings.sweep_param_path
        if sweep_path:
            self._sweep_config = config_util.dict_from_config_file(
                sweep_path, must_exist=True
            )

        # if config_paths was set, read in config dict
        if self._settings.config_paths:
            # TODO(jhr): handle load errors, handle list of files
            for config_path in self._settings.config_paths:
                config_dict = config_util.dict_from_config_file(config_path)
                if config_dict is None:
                    continue
                if self._config is not None:
                    self._config.update(config_dict)
                else:
                    self._config = config_dict

    def _teardown(self, exit_code: int | None = None) -> None:
        import_hooks.unregister_all_post_import_hooks()

        if not self._connection:
            return

        internal_exit_code = self._connection.teardown(exit_code or 0)

        # Reset to None so that setup() creates a new connection.
        self._connection = None

        if internal_exit_code != 0:
            sys.exit(internal_exit_code)

    def ensure_service(self) -> ServiceConnection:
        """Returns a connection to the service process creating it if needed."""
        if self._connection:
            return self._connection

        from wandb.sdk.lib import service_connection

        self._connection = service_connection.connect_to_service(self._settings)
        return self._connection

    def assert_service(self) -> ServiceConnection:
        """Returns a connection to the service process, asserting it exists.

        Unlike ensure_service(), this will not start up a service process
        if it didn't already exist.
        """
        if not self._connection:
            raise AssertionError("Expected service process to exist.")

        return self._connection


_singleton: _WandbSetup | None = None
"""The W&B library singleton, or None if not yet set up.

The value is invalid and must not be used if `os.getpid() != _singleton._pid`.
"""


def singleton() -> _WandbSetup | None:
    """Returns the W&B singleton if it exists for the current process.

    Unlike setup(), this does not create the singleton if it doesn't exist.
    """
    if _singleton and _singleton._pid == os.getpid():
        return _singleton
    else:
        return None


@wb_logging.log_to_all_runs()
def _setup(
    settings: Settings | None = None,
    start_service: bool = True,
) -> _WandbSetup:
    """Set up library context.

    Args:
        settings: Global settings to set, or updates to the global settings
            if the singleton has already been initialized.
        start_service: Whether to start up the service process.
            NOTE: A service process will only be started if allowed by the
            global settings (after the given updates). The service will not
            start up if the mode resolves to "disabled".
    """
    global _singleton

    pid = os.getpid()

    if _singleton and _singleton._pid == pid:
        _singleton._update(settings=settings)
    else:
        _singleton = _WandbSetup(settings=settings, pid=pid)

    if start_service and not _singleton.settings._noop:
        _singleton.ensure_service()

    return _singleton


def setup(settings: Settings | None = None) -> _WandbSetup:
    """Prepares W&B for use in the current process and its children.

    You can usually ignore this as it is implicitly called by `wandb.init()`.

    When using wandb in multiple processes, calling `wandb.setup()`
    in the parent process before starting child processes may improve
    performance and resource utilization.

    Note that `wandb.setup()` modifies `os.environ`, and it is important
    that child processes inherit the modified environment variables.

    See also `wandb.teardown()`.

    Args:
        settings: Configuration settings to apply globally. These can be
            overridden by subsequent `wandb.init()` calls.

    Example:
        ```python
        import multiprocessing

        import wandb


        def run_experiment(params):
            with wandb.init(config=params):
                # Run experiment
                pass


        if __name__ == "__main__":
            # Start backend and set global config
            wandb.setup(settings={"project": "my_project"})

            # Define experiment parameters
            experiment_params = [
                {"learning_rate": 0.01, "epochs": 10},
                {"learning_rate": 0.001, "epochs": 20},
            ]

            # Start multiple processes, each running a separate experiment
            processes = []
            for params in experiment_params:
                p = multiprocessing.Process(target=run_experiment, args=(params,))
                p.start()
                processes.append(p)

            # Wait for all processes to complete
            for p in processes:
                p.join()

            # Optional: Explicitly shut down the backend
            wandb.teardown()
        ```
    """
    return _setup(settings=settings)


@wb_logging.log_to_all_runs()
def teardown(exit_code: int | None = None) -> None:
    """Waits for wandb to finish and frees resources.

    Completes any runs that were not explicitly finished
    using `run.finish()` and waits for all data to be uploaded.

    It is recommended to call this at the end of a session
    that used `wandb.setup()`. It is invoked automatically
    in an `atexit` hook, but this is not reliable in certain setups
    such as when using Python's `multiprocessing` module.
    """
    global _singleton

    orig_singleton = _singleton
    _singleton = None

    if orig_singleton:
        orig_singleton._teardown(exit_code=exit_code)
