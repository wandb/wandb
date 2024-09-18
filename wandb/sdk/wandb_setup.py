#
"""Setup wandb session.

This module configures a wandb session which can extend to multiple wandb runs.

Functions:
    setup(): Configure wandb session.

Early logging keeps track of logger output until the call to wandb.init() when the
run_id can be resolved.

"""

import logging
import os
import sys
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import wandb
from wandb.sdk.lib import import_hooks

from . import wandb_settings
from .lib import config_util, server, tracelog

Settings = Union["wandb.sdk.wandb_settings.Settings", Dict[str, Any]]

Logger = Union[logging.Logger, "_EarlyLogger"]

if TYPE_CHECKING:
    from wandb.sdk.lib import service_connection

    from . import wandb_run

# logger will be configured to be either a standard logger instance or _EarlyLogger
logger: Optional[Logger] = None


def _set_logger(log_object: Logger) -> None:
    """Configure module logger."""
    global logger
    logger = log_object


class _EarlyLogger:
    """Early logger which captures logs in memory until logging can be configured."""

    def __init__(self) -> None:
        self._log: List[tuple] = []
        self._exception: List[tuple] = []
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

    def _flush(self) -> None:
        assert self is not logger
        assert logger is not None
        for level, msg, args, kwargs in self._log:
            logger.log(level, msg, *args, **kwargs)
        for msg, args, kwargs in self._exception:
            logger.exception(msg, *args, **kwargs)


class _WandbSetup__WandbSetup:  # noqa: N801
    """Inner class of _WandbSetup."""

    def __init__(
        self,
        pid: int,
        settings: Optional[Settings] = None,
        environ: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._connection: Optional[service_connection.ServiceConnection] = None

        self._environ = environ or dict(os.environ)
        self._sweep_config: Optional[Dict[str, Any]] = None
        self._config: Optional[Dict[str, Any]] = None
        self._server: Optional[server.Server] = None
        self._pid = pid

        # keep track of multiple runs, so we can unwind with join()s
        self._global_run_stack: List[wandb_run.Run] = []

        # TODO(jhr): defer strict checks until settings are fully initialized
        #            and logging is ready
        self._early_logger = _EarlyLogger()
        _set_logger(self._early_logger)

        self._settings = self._settings_setup(settings, self._early_logger)
        # self._settings.freeze()

        wandb.termsetup(self._settings, logger)

        self._check()
        self._setup()

        tracelog_mode = self._settings._tracelog
        if tracelog_mode:
            tracelog.enable(tracelog_mode)

    def _settings_setup(
        self,
        settings: Optional[Settings] = None,
        early_logger: Optional[_EarlyLogger] = None,
    ) -> "wandb_settings.Settings":
        s = wandb_settings.Settings()
        s._apply_base(pid=self._pid, _logger=early_logger)
        s._apply_config_files(_logger=early_logger)
        s._apply_env_vars(self._environ, _logger=early_logger)

        if isinstance(settings, wandb_settings.Settings):
            s._apply_settings(settings, _logger=early_logger)
        elif isinstance(settings, dict):
            # if passed settings arg is a mapping, update the settings with it
            s._apply_setup(settings, _logger=early_logger)

        s._infer_settings_from_environment()
        if not s._cli_only_mode:
            s._infer_run_settings_from_environment(_logger=early_logger)

        return s

    def _update(
        self,
        settings: Optional[Settings] = None,
    ) -> None:
        if settings is None:
            return
        # self._settings.unfreeze()
        if isinstance(settings, wandb_settings.Settings):
            # todo: check the logic here. this _only_ comes up in tests?
            self._settings._apply_settings(settings)
        elif isinstance(settings, dict):
            # if it is a mapping, update the settings with it
            self._settings.update(settings, source=wandb_settings.Source.SETUP)
        # self._settings.freeze()

    def _update_user_settings(self, settings: Optional[Settings] = None) -> None:
        settings = settings or self._settings
        # Get rid of cached results to force a refresh.
        self._server = None
        user_settings = self._load_user_settings(settings=settings)
        if user_settings is not None:
            # self._settings.unfreeze()
            self._settings._apply_user(user_settings)
            # self._settings.freeze()

    def _early_logger_flush(self, new_logger: Logger) -> None:
        if not self._early_logger:
            return
        _set_logger(new_logger)
        # self._settings._clear_early_logger()
        self._early_logger._flush()

    def _get_logger(self) -> Optional[Logger]:
        return logger

    @property
    def settings(self) -> "wandb_settings.Settings":
        return self._settings

    def _get_entity(self) -> Optional[str]:
        if self._settings and self._settings._offline:
            return None
        if self._server is None:
            self._load_viewer()
        assert self._server is not None
        entity = self._server._viewer.get("entity")
        return entity

    def _get_username(self) -> Optional[str]:
        if self._settings and self._settings._offline:
            return None
        if self._server is None:
            self._load_viewer()
        assert self._server is not None
        username = self._server._viewer.get("username")
        return username

    def _get_teams(self) -> List[str]:
        if self._settings and self._settings._offline:
            return []
        if self._server is None:
            self._load_viewer()
        assert self._server is not None
        teams = self._server._viewer.get("teams")
        if teams:
            teams = [team["node"]["name"] for team in teams["edges"]]
        return teams or []

    def _load_viewer(self, settings: Optional[Settings] = None) -> None:
        if self._settings and self._settings._offline:
            return
        if isinstance(settings, dict):
            settings = wandb_settings.Settings(**settings)
        s = server.Server(settings=settings)
        s.query_with_timeout()
        self._server = s

    def _load_user_settings(
        self, settings: Optional[Settings] = None
    ) -> Optional[Dict[str, Any]]:
        if self._server is None:
            self._load_viewer(settings=settings)

        # offline?
        if self._server is None:
            return None

        flags = self._server._flags
        user_settings = dict()
        if "code_saving_enabled" in flags:
            user_settings["save_code"] = flags["code_saving_enabled"]

        email = self._server._viewer.get("email", None)
        if email:
            user_settings["email"] = email

        return user_settings

    def _check(self) -> None:
        if hasattr(threading, "main_thread"):
            if threading.current_thread() is not threading.main_thread():
                pass
        elif threading.current_thread().name != "MainThread":
            print("bad thread2", threading.current_thread().name)
        if getattr(sys, "frozen", False):
            print("frozen, could be trouble")

    def _setup(self) -> None:
        if not self._settings._noop and not self._settings._disable_service:
            from wandb.sdk.lib import service_connection

            self._connection = service_connection.connect_to_service(self._settings)

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

    def _teardown(self, exit_code: Optional[int] = None) -> None:
        import_hooks.unregister_all_post_import_hooks()

        if not self._connection:
            return

        internal_exit_code = self._connection.teardown(exit_code or 0)

        # Reset to None so that setup() creates a new connection.
        self._connection = None

        if internal_exit_code != 0:
            sys.exit(internal_exit_code)

    @property
    def service(self) -> "Optional[service_connection.ServiceConnection]":
        """Returns a connection to the service process, if it exists."""
        return self._connection


class _WandbSetup:
    """Wandb singleton class.

    Note: This is a process local singleton.
    (Forked processes will get a new copy of the object)
    """

    _instance: Optional["_WandbSetup__WandbSetup"] = None

    def __init__(self, settings: Optional[Settings] = None) -> None:
        pid = os.getpid()
        if _WandbSetup._instance and _WandbSetup._instance._pid == pid:
            _WandbSetup._instance._update(settings=settings)
            return
        _WandbSetup._instance = _WandbSetup__WandbSetup(settings=settings, pid=pid)

    @property
    def service(self) -> "Optional[service_connection.ServiceConnection]":
        """Returns a connection to the service process, if it exists."""
        if not self._instance:
            return None
        return self._instance.service

    def __getattr__(self, name: str) -> Any:
        return getattr(self._instance, name)


def _setup(
    settings: Optional[Settings] = None,
    _reset: bool = False,
) -> Optional["_WandbSetup"]:
    """Set up library context."""
    if _reset:
        teardown()
        return None

    wl = _WandbSetup(settings=settings)
    return wl


def setup(settings: Optional[Settings] = None) -> Optional["_WandbSetup"]:
    """Prepares W&B for use in the current process and its children.

    You can usually ignore this as it is implicitly called by `wandb.init()`.

    When using wandb in multiple processes, calling `wandb.setup()`
    in the parent process before starting child processes may improve
    performance and resource utilization.

    Note that `wandb.setup()` modifies `os.environ`, and it is important
    that child processes inherit the modified environment variables.

    See also `wandb.teardown()`.

    Args:
        settings (Optional[Union[Dict[str, Any], wandb.Settings]]): Configuration settings
            to apply globally. These can be overridden by subsequent `wandb.init()` calls.

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
    ret = _setup(settings=settings)
    return ret


def teardown(exit_code: Optional[int] = None) -> None:
    """Waits for wandb to finish and frees resources.

    Completes any runs that were not explicitly finished
    using `run.finish()` and waits for all data to be uploaded.

    It is recommended to call this at the end of a session
    that used `wandb.setup()`. It is invoked automatically
    in an `atexit` hook, but this is not reliable in certain setups
    such as when using Python's `multiprocessing` module.
    """
    setup_instance = _WandbSetup._instance
    _WandbSetup._instance = None

    if setup_instance:
        setup_instance._teardown(exit_code=exit_code)
