# -*- coding: utf-8 -*-
"""
init.
"""

from __future__ import print_function

import datetime
import logging
import os
import time
import traceback

from six import iteritems, raise_from
import wandb
from wandb import trigger
from wandb.backend.backend import Backend
from wandb.errors.error import UsageError
from wandb.integration.magic import magic_install
from wandb.lib import console as lib_console
from wandb.lib import filesystem, module, reporting
from wandb.old import io_wrap
from wandb.util import sentry_exc

from .wandb_helper import parse_config
from .wandb_login import _login
from .wandb_run import Run, RunDummy, RunManaged
from .wandb_settings import Settings

if wandb.TYPE_CHECKING:  # type: ignore
    from typing import Optional, Union, List, Dict, Any  # noqa: F401

logger = None  # logger configured during wandb.init()


def _set_logger(log_object):
    """Configure module logger."""
    global logger
    logger = log_object


def online_status(*args, **kwargs):
    pass


class _WandbInit(object):
    def __init__(self):
        self.kwargs = None
        self.settings = None
        self.config = None
        self.run = None
        self.backend = None

        self._teardown_hooks = []
        self._wl = None
        self._reporter = None

    def setup(self, kwargs):
        """Complete setup for wandb.init().

        This includes parsing all arguments, applying them with settings and enabling
        logging.

        """
        self.kwargs = kwargs
        # Some settings should be persisted across multiple runs the first
        # time setup is called.
        # TODO: Is this the best way to do this?
        session_settings_keys = ["anonymous"]
        session_settings = {k: kwargs[k] for k in session_settings_keys}
        self._wl = wandb.setup(settings=session_settings, _warn=False)
        # Make sure we have a logger setup (might be an early logger)
        _set_logger(self._wl._get_logger())

        settings: Settings = self._wl.settings(
            dict(kwargs.pop("settings", None) or tuple())
        )

        self._reporter = reporting.setup_reporter(
            settings=settings.duplicate().freeze()
        )

        # Remove parameters that are not part of settings
        init_config = kwargs.pop("config", None) or dict()
        config_include_keys = kwargs.pop("config_include_keys", None)
        config_exclude_keys = kwargs.pop("config_exclude_keys", None)

        if config_include_keys or config_exclude_keys:
            wandb.termwarn(
                "config_include_keys and config_exclude_keys are deprecated -- instead,"
                " use config=wandb.helper.parse_config(config_object, include=('key',))"
                " or config=wandb.helper.parse_config(config_object, exclude=('key',))"
            )

        if config_exclude_keys and config_include_keys:
            raise UsageError(
                "Expected at most only one of config_exclude_keys or "
                "config_include_keys"
            )
        init_config = parse_config(
            init_config, include=config_include_keys, exclude=config_exclude_keys
        )
        if config_include_keys:
            init_config = {
                key: value
                for key, value in iteritems(init_config)
                if key in config_include_keys
            }
        if config_exclude_keys:
            init_config = {
                key: value
                for key, value in iteritems(init_config)
                if key not in config_exclude_keys
            }

        # merge config with sweep (or config file)
        self.config = self._wl._config or dict()
        for k, v in init_config.items():
            self.config.setdefault(k, v)

        # Temporarily unsupported parameters
        unsupported = (
            "allow_val_change",
            "force",
        )
        for key in unsupported:
            val = kwargs.pop(key, None)
            if val:
                self._reporter.warning(
                    "currently unsupported wandb.init() arg: %s", key
                )

        monitor_gym = kwargs.pop("monitor_gym", None)
        if monitor_gym and len(wandb.patched["gym"]) == 0:
            wandb.gym.monitor()

        tensorboard = kwargs.pop("tensorboard", None)
        sync_tensorboard = kwargs.pop("sync_tensorboard", None)
        if tensorboard or sync_tensorboard and len(wandb.patched["tensorboard"]) == 0:
            wandb.tensorboard.patch()

        magic = kwargs.get("magic")
        if magic not in (None, False):
            magic_install(kwargs)

        # prevent setting project, entity if in sweep
        # TODO(jhr): these should be locked elements in the future or at least
        #            moved to apply_init()
        if settings.sweep_id:
            for key in ("project", "entity"):
                val = kwargs.pop(key, None)
                if val:
                    print("Ignored wandb.init() arg %s when running a sweep" % key)
        settings.apply_init(kwargs)

        # TODO(jhr): should this be moved? probably.
        d = dict(_start_time=time.time(), _start_datetime=datetime.datetime.now(),)
        settings.update(d)

        if settings.jupyter:
            self._jupyter_setup(settings)

        self._log_setup(settings)

        self.settings = settings.freeze()

    def teardown(self):
        # TODO: currently this is only called on failed wandb.init attempts
        # normally this happens on the run object
        logger.info("tearing down wandb.init")
        for hook in self._teardown_hooks:
            hook()

    def _enable_logging(self, log_fname, run_id=None):
        """Enable logging to the global debug log.  This adds a run_id to the log,
        in case of muliple processes on the same machine.

        Currently no way to disable logging after it's enabled.
        """
        handler = logging.FileHandler(log_fname)
        handler.setLevel(logging.INFO)

        class WBFilter(logging.Filter):
            def filter(self, record):
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
        logger.propagate = False
        logger.addHandler(handler)
        # TODO: make me configurable
        logger.setLevel(logging.DEBUG)
        # TODO: we may need to close the handler as well...
        self._teardown_hooks.append(lambda: logger.removeHandler(handler))

    def _safe_symlink(self, base, target, name, delete=False):
        # TODO(jhr): do this with relpaths, but i cant figure it out on no sleep
        if not hasattr(os, "symlink"):
            return

        pid = os.getpid()
        tmp_name = "%s.%d" % (name, pid)
        owd = os.getcwd()
        os.chdir(base)
        if delete:
            try:
                os.remove(name)
            except OSError:
                pass
        target = os.path.relpath(target, base)
        os.symlink(target, tmp_name)
        os.rename(tmp_name, name)
        os.chdir(owd)

    def _pause_backend(self):
        if self.backend is not None:
            logger.info("pausing backend")
            self.backend.interface.publish_pause()

    def _resume_backend(self):
        if self.backend is not None:
            logger.info("resuming backend")
            self.backend.interface.publish_resume()

    def _jupyter_teardown(self):
        """Teardown hooks and display saving, called with wandb.join"""
        logger.info("cleaning up jupyter logic")
        ipython = self.notebook.shell
        self.notebook.save_history()
        # because of how we bind our methods we manually find them to unregister
        for hook in ipython.events.callbacks["pre_run_cell"]:
            if "_resume_backend" in hook.__name__:
                ipython.events.unregister("pre_run_cell", hook)
        for hook in ipython.events.callbacks["post_run_cell"]:
            if "_pause_backend" in hook.__name__:
                ipython.events.unregister("post_run_cell", hook)
        ipython.display_pub.publish = ipython.display_pub._orig_publish
        del ipython.display_pub._orig_publish

    def _jupyter_setup(self, settings):
        """Add magic, hooks, and session history saving"""
        self.notebook = wandb.jupyter.Notebook(settings)
        ipython = self.notebook.shell
        ipython.register_magics(wandb.jupyter.WandBMagics)

        # Monkey patch ipython publish to capture displayed outputs
        if not hasattr(ipython.display_pub, "_orig_publish"):
            logger.info("configuring jupyter hooks %s", self)
            ipython.display_pub._orig_publish = ipython.display_pub.publish
            # Registering resume and pause hooks

            ipython.events.register("pre_run_cell", self._resume_backend)
            ipython.events.register("post_run_cell", self._pause_backend)
            self._teardown_hooks.append(self._jupyter_teardown)

        def publish(data, metadata=None, **kwargs):
            ipython.display_pub._orig_publish(data, metadata=metadata, **kwargs)
            self.notebook.save_display(
                ipython.execution_count, {"data": data, "metadata": metadata}
            )

        ipython.display_pub.publish = publish

    def _log_setup(self, settings):
        """Setup logging from settings."""

        settings.log_user = settings._path_convert(
            settings.log_dir_spec, settings.log_user_spec
        )
        settings.log_internal = settings._path_convert(
            settings.log_dir_spec, settings.log_internal_spec
        )
        settings._sync_dir = settings._path_convert(settings.sync_dir_spec)
        settings.sync_file = settings._path_convert(
            settings.sync_dir_spec, settings.sync_file_spec
        )
        settings.files_dir = settings._path_convert(settings.files_dir_spec)
        filesystem._safe_makedirs(os.path.dirname(settings.log_user))
        filesystem._safe_makedirs(os.path.dirname(settings.log_internal))
        filesystem._safe_makedirs(os.path.dirname(settings.sync_file))
        filesystem._safe_makedirs(settings.files_dir)

        log_symlink_user = settings._path_convert(settings.log_symlink_user_spec)
        log_symlink_internal = settings._path_convert(
            settings.log_symlink_internal_spec
        )
        sync_symlink_latest = settings._path_convert(settings.sync_symlink_latest_spec)

        if settings.symlink:
            self._safe_symlink(
                os.path.dirname(sync_symlink_latest),
                os.path.dirname(settings.sync_file),
                os.path.basename(sync_symlink_latest),
                delete=True,
            )
            self._safe_symlink(
                os.path.dirname(log_symlink_user),
                settings.log_user,
                os.path.basename(log_symlink_user),
                delete=True,
            )
            self._safe_symlink(
                os.path.dirname(log_symlink_internal),
                settings.log_internal,
                os.path.basename(log_symlink_internal),
                delete=True,
            )

        _set_logger(logging.getLogger("wandb"))
        self._enable_logging(settings.log_user)

        logger.info("Logging user logs to {}".format(settings.log_user))
        logger.info("Logging internal logs to {}".format(settings.log_internal))

        self._wl._early_logger_flush(logger)

    def init(self):
        trigger.call("on_init", **self.kwargs)
        s = self.settings
        config = self.config

        if s.reinit or (s.jupyter and s.reinit is not False):
            if len(self._wl._global_run_stack) > 0:
                if len(self._wl._global_run_stack) > 1:
                    wandb.termwarn(
                        "If you want to track multiple runs concurrently in wandb you should use multi-processing not threads"  # noqa: E501
                    )
                self._wl._global_run_stack[-1].join()
        elif wandb.run:
            logger.info("wandb.init() called when a run is still active")
            return wandb.run

        console = s.console
        use_redirect = True
        stdout_master_fd, stderr_master_fd = None, None
        stdout_slave_fd, stderr_slave_fd = None, None
        if console == "iowrap":
            stdout_master_fd, stdout_slave_fd = io_wrap.wandb_pty(resize=False)
            stderr_master_fd, stderr_slave_fd = io_wrap.wandb_pty(resize=False)
        elif console == "_win32":
            # Not used right now
            stdout_master_fd, stdout_slave_fd = lib_console.win32_create_pipe()
            stderr_master_fd, stderr_slave_fd = lib_console.win32_create_pipe()

        backend = Backend()
        backend.ensure_launched(
            settings=s,
            stdout_fd=stdout_master_fd,
            stderr_fd=stderr_master_fd,
            use_redirect=use_redirect,
        )
        backend.server_connect()
        # Make sure we are logged in
        _login(_backend=backend, _disable_warning=True, _settings=self.settings)

        # resuming needs access to the server, check server_status()?

        run = RunManaged(config=config, settings=s)
        run._set_console(
            use_redirect=use_redirect,
            stdout_slave_fd=stdout_slave_fd,
            stderr_slave_fd=stderr_slave_fd,
        )
        run._set_library(self._wl)
        run._set_backend(backend)
        run._set_reporter(self._reporter)
        run._set_teardown_hooks(self._teardown_hooks)
        # TODO: pass mode to backend
        # run_synced = None

        backend._hack_set_run(run)

        if s.offline:
            backend.interface.publish_run(run)
        else:
            ret = backend.interface.communicate_check_version()
            message = ret.response.check_version_response.message
            if message:
                wandb.termlog(message)

            ret = backend.interface.communicate_run(run, timeout=30)
            # TODO: fail on more errors, check return type
            # TODO: make the backend log stacktraces on catostrophic failure
            if ret.HasField("error"):
                # Shutdown the backend and get rid of the logger
                # we don't need to do console cleanup at this point
                backend.cleanup()
                self.teardown()
                raise UsageError(ret.error.message)
            run._set_run_obj(ret.run)

        # initiate run (stats and metadata probing)
        _ = backend.interface.communicate_run_start()

        self._wl._global_run_stack.append(run)
        self.run = run
        self.backend = backend
        module.set_global(
            run=run,
            config=run.config,
            log=run.log,
            join=run.join,
            summary=run.summary,
            save=run.save,
            restore=run.restore,
            use_artifact=run.use_artifact,
            log_artifact=run.log_artifact,
        )
        self._reporter.set_context(run=run)
        run._on_start()

        return run


def getcaller():
    # py2 doesnt have stack_info
    # src, line, func, stack = logger.findCaller(stack_info=True)
    src, line, func = logger.findCaller()[:3]
    print("Problem at:", src, line, func)


def init(
    job_type: Optional[str] = None,
    dir=None,
    config: Union[Dict, None] = None,  # TODO(jhr): type is a union for argparse/absl
    project: Optional[str] = None,
    entity: Optional[str] = None,
    reinit: bool = None,
    tags: Optional[List] = None,
    group: Optional[str] = None,
    name: Optional[str] = None,
    notes: Optional[str] = None,
    magic: Union[dict, str, bool] = None,  # TODO(jhr): type is union
    config_exclude_keys=None,
    config_include_keys=None,
    anonymous: Optional[str] = None,
    mode: Optional[str] = None,
    allow_val_change: bool = None,
    resume: Optional[Union[bool, str]] = None,
    force=None,
    tensorboard=None,  # alias for sync_tensorboard
    sync_tensorboard=None,
    monitor_gym=None,
    id=None,
    settings: Union[Settings, Dict[str, Any], str, None] = None,
) -> Run:
    """Initialize a wandb Run.

    Args:
        entity: alias for team.
        team: personal user or team to use for Run.
        project: project name for the Run.

    Raises:
        Exception: if problem.

    Returns:
        wandb Run object

    """
    assert not wandb._IS_INTERNAL_PROCESS
    kwargs = locals()
    error_seen = None
    except_exit = None
    try:
        wi = _WandbInit()
        wi.setup(kwargs)
        except_exit = wi.settings._except_exit
        try:
            run = wi.init()
            except_exit = wi.settings._except_exit
        except (KeyboardInterrupt, Exception) as e:
            if not isinstance(e, KeyboardInterrupt):
                sentry_exc(e)
            getcaller()
            assert logger
            if wi.settings.problem == "fatal":
                raise
            if wi.settings.problem == "warn":
                pass
            run = RunDummy()
    except UsageError:
        raise
    except KeyboardInterrupt as e:
        assert logger
        logger.warning("interrupted", exc_info=e)
        raise_from(Exception("interrupted"), e)
    except Exception as e:
        error_seen = e
        traceback.print_exc()
        assert logger
        logger.error("error", exc_info=e)
        # Need to build delay into this sentry capture because our exit hooks
        # mess with sentry's ability to send out errors before the program ends.
        sentry_exc(e, delay=True)
        # reraise(*sys.exc_info())
        # raise_from(Exception("problem"), e)
    finally:
        if error_seen:
            wandb.termerror("Abnormal program exit")
            if except_exit:
                os._exit(-1)
            raise_from(Exception("problem"), error_seen)
    return run
