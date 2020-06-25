# -*- coding: utf-8 -*-
"""
init.
"""

from __future__ import print_function

import atexit
import datetime
import logging
import os
import platform
import sys
import time
import traceback

from six import raise_from
import wandb
from wandb.backend.backend import Backend
from wandb.errors import Error
from wandb.lib import filesystem, redirect, reporting
from wandb.lib.globals import set_global
from wandb.old import io_wrap
from wandb.util import sentry_exc

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


class ExitHooks(object):
    def __init__(self):
        self.exit_code = 0
        self.exception = None

    def hook(self):
        self._orig_exit = sys.exit
        sys.exit = self.exit
        sys.excepthook = self.exc_handler

    def exit(self, code=0):
        orig_code = code
        if code is None:
            code = 0
        elif not isinstance(code, int):
            code = 1
        self.exit_code = code
        self._orig_exit(orig_code)

    def was_ctrl_c(self):
        return isinstance(self.exception, KeyboardInterrupt)

    def exc_handler(self, exc_type, exc, *tb):
        self.exit_code = 1
        self.exception = exc
        if issubclass(exc_type, Error):
            wandb.termerror(str(exc))

        if self.was_ctrl_c():
            self.exit_code = 255

        print("except handle")
        traceback.print_exception(exc_type, exc, *tb)


def win32_redirect(stdout_slave_fd, stderr_slave_fd):
    # import win32api

    # save for later
    # fd_stdout = os.dup(1)
    # fd_stderr = os.dup(2)

    # std_out = win32api.GetStdHandle(win32api.STD_OUTPUT_HANDLE)
    # std_err = win32api.GetStdHandle(win32api.STD_ERROR_HANDLE)

    # os.dup2(stdout_slave_fd, 1)
    # os.dup2(stderr_slave_fd, 2)

    # TODO(jhr): do something about current stdout, stderr file handles
    pass


def win32_create_pipe():
    # import pywintypes
    # import win32pipe

    # sa=pywintypes.SECURITY_ATTRIBUTES()
    # sa.bInheritHandle=1

    # read_fd, write_fd = win32pipe.FdCreatePipe(sa, 0, os.O_TEXT)
    # read_fd, write_fd = win32pipe.FdCreatePipe(sa, 0, os.O_BINARY)
    read_fd, write_fd = os.pipe()
    # http://timgolden.me.uk/pywin32-docs/win32pipe__FdCreatePipe_meth.html
    # https://stackoverflow.com/questions/17942874/stdout-redirection-with-ctypes

    # f = open("testing.txt", "rb")
    # read_fd = f.fileno()

    return read_fd, write_fd


class _WandbInit(object):
    def __init__(self):
        self.kwargs = None
        self.settings = None
        self.config = None
        self.wl = None
        self.run = None
        self.backend = None

        self._use_redirect = True
        self._redirect_cb = None
        self._out_redir = None
        self._err_redir = None
        self._reporter = None

        # move this
        self.stdout_redirector = None
        self.stderr_redirector = None
        self._save_stdout = None
        self._save_stderr = None

        self._hooks = None
        self._atexit_cleanup_called = None

    def setup(self, kwargs):
        """Complete setup for wandb.init().

        This includes parsing all arguments, applying them with settings and enabling
        logging.

        """
        self.kwargs = kwargs

        wl = wandb.setup()
        # Make sure we have a logger setup (might be an early logger)
        _set_logger(wl._get_logger())

        settings: Settings = wl.settings(dict(kwargs.pop("settings", None) or tuple()))

        self._reporter = reporting.setup_reporter(
            settings=settings.duplicate().freeze()
        )

        # Remove parameters that are not part of settings
        init_config = kwargs.pop("config", None) or dict()

        # merge config with sweep (or config file)
        self.config = wl._config or dict()
        for k, v in init_config.items():
            self.config.setdefault(k, v)

        # Temporarily unsupported parameters
        unsupported = (
            "magic",
            "config_exclude_keys",
            "config_include_keys",
            "reinit",
            "anonymous",
            "dir",
            "allow_val_change",
            "resume",
            "force",
            "tensorboard",
            "sync_tensorboard",
            "monitor_gym",
        )
        for key in unsupported:
            val = kwargs.pop(key, None)
            if val:
                self._reporter.warning(
                    "currently unsupported wandb.init() arg: %s", key
                )

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

        self._log_setup(settings)
        wl._early_logger_flush(logger)

        self.wl = wl
        self.settings = settings.freeze()

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
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

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

    def _log_setup(self, settings):
        """Setup logging from settings."""

        settings.log_user = settings._path_convert(
            settings.log_dir_spec, settings.log_user_spec
        )
        settings.log_internal = settings._path_convert(
            settings.log_dir_spec, settings.log_internal_spec
        )
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

    def _atexit_cleanup(self):
        if self._atexit_cleanup_called:
            return
        self._atexit_cleanup_called = True

        exit_code = self._hooks.exit_code if self._hooks else 0
        logger.info("got exitcode: %d", exit_code)
        ret = self.backend.interface.send_exit_sync(exit_code, timeout=60)
        logger.info("got exit ret: %s", ret)
        if ret is None:
            print("Problem syncing data")
            os._exit(1)

        self._restore()

        self.backend.cleanup()
        # TODO(jhr): no warning allowed
        if self.run:
            self.run.on_finish()

    def _callback(self, name, data):
        logger.info("callback: %s, %s", name, data)
        self.backend.interface.send_output(name, data)

    def _redirect(self, stdout_slave_fd, stderr_slave_fd):
        console = self.settings.console
        logger.info("redirect: %s", console)

        if console == "redirect":
            logger.info("redirect1")
            out_cap = redirect.Capture(name="stdout", cb=self._redirect_cb)
            out_redir = redirect.Redirect(
                src="stdout", dest=out_cap, unbuffered=True, tee=True
            )
            err_cap = redirect.Capture(name="stderr", cb=self._redirect_cb)
            err_redir = redirect.Redirect(
                src="stderr", dest=err_cap, unbuffered=True, tee=True
            )
            out_redir.install()
            err_redir.install()
            self._out_redir = out_redir
            self._err_redir = err_redir
            logger.info("redirect2")
            return

        return

        # redirect stdout
        if platform.system() == "Windows":
            win32_redirect(stdout_slave_fd, stderr_slave_fd)
        else:
            self._save_stdout = sys.stdout
            self._save_stderr = sys.stderr
            stdout_slave = os.fdopen(stdout_slave_fd, "wb")
            stderr_slave = os.fdopen(stderr_slave_fd, "wb")
            stdout_redirector = io_wrap.FileRedirector(sys.stdout, stdout_slave)
            stderr_redirector = io_wrap.FileRedirector(sys.stderr, stderr_slave)
            stdout_redirector.redirect()
            stderr_redirector.redirect()
            self.stdout_redirector = stdout_redirector
            self.stderr_redirector = stderr_redirector
        logger.info("redirect done")

    def _restore(self):
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

    def init(self):
        s = self.settings
        config = self.config

        if s.mode == "noop":
            # TODO(jhr): return dummy object
            return None

        # Make sure we are logged in
        wandb.login()

        stdout_master_fd = None
        stderr_master_fd = None
        stdout_slave_fd = None
        stderr_slave_fd = None
        console = s.console

        if console == "redirect":
            pass
        elif console == "off":
            pass
        elif console == "mock":
            pass
        elif console == "file":
            pass
        elif console == "iowrap":
            stdout_master_fd, stdout_slave_fd = io_wrap.wandb_pty(resize=False)
            stderr_master_fd, stderr_slave_fd = io_wrap.wandb_pty(resize=False)
        elif console == "_win32":
            # Not used right now
            stdout_master_fd, stdout_slave_fd = win32_create_pipe()
            stderr_master_fd, stderr_slave_fd = win32_create_pipe()
        else:
            self._reporter.internal("Unknown console: %s", console)

        backend = Backend(mode=s.mode)
        backend.ensure_launched(
            settings=s,
            stdout_fd=stdout_master_fd,
            stderr_fd=stderr_master_fd,
            use_redirect=self._use_redirect,
        )
        backend.server_connect()

        # resuming needs access to the server, check server_status()?

        run = RunManaged(config=config, settings=s)
        run._set_backend(backend)
        run._set_reporter(self._reporter)
        # TODO: pass mode to backend
        # run_synced = None

        backend._hack_set_run(run)

        if s.mode == "online":
            ret = backend.interface.send_run_sync(run, timeout=30)
            # TODO: fail on error, check return type
            run._set_run_obj(ret.run)
        elif s.mode in ("offline", "dryrun"):
            backend.interface.send_run(run)
        elif s.mode in ("async", "run"):
            ret = backend.interface.send_run_sync(run, timeout=10)
            # TODO: on network error, do async run save
            backend.interface.send_run(run)

        self.run = run
        self.backend = backend
        set_global(run=run, config=run.config, log=run.log, join=run.join)
        self._reporter.set_context(run=run)
        run.on_start()

        logger.info("atexit reg")
        self._hooks = ExitHooks()
        self._hooks.hook()
        atexit.register(lambda: self._atexit_cleanup())

        if self._use_redirect:
            # setup fake callback
            self._redirect_cb = self._callback

        self._redirect(stdout_slave_fd, stderr_slave_fd)

        # for super agent
        # run._save_job_spec()

        return run


def getcaller():
    # py2 doesnt have stack_info
    # src, line, func, stack = logger.findCaller(stack_info=True)
    src, line, func = logger.findCaller()[:3]
    print("Problem at:", src, line, func)


def init(
    settings: Union[Settings, Dict[str, Any], str, None] = None,
    entity: Optional[str] = None,
    team: Optional[str] = None,
    project: Optional[str] = None,
    mode: Optional[str] = None,
    group: Optional[str] = None,
    job_type: Optional[str] = None,
    tags: Optional[List] = None,
    name: Optional[str] = None,
    config: Union[Dict, None] = None,  # TODO(jhr): type is a union for argparse/absl
    notes: Optional[str] = None,
    magic: bool = None,  # TODO(jhr): type is union
    config_exclude_keys=None,
    config_include_keys=None,
    reinit: bool = None,
    anonymous: bool = None,
    dir=None,
    allow_val_change=None,
    resume=None,
    force=None,
    tensorboard=None,
    sync_tensorboard=None,
    monitor_gym=None,
    id=None,
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
    try:
        wi = _WandbInit()
        wi.setup(kwargs)
        try:
            run = wi.init()
        except (KeyboardInterrupt, Exception) as e:
            if not isinstance(e, KeyboardInterrupt):
                sentry_exc(e)
            getcaller()
            assert logger
            logger.exception("we got issues")
            wi._atexit_cleanup()
            if wi.settings.problem == "fatal":
                raise
            if wi.settings.problem == "warn":
                pass
            run = RunDummy()
    except KeyboardInterrupt as e:
        assert logger
        logger.warning("interupted", exc_info=e)
        raise_from(Exception("interrupted"), e)
    except Exception as e:
        assert logger
        logger.error("error", exc_info=e)
        # Need to build delay into this sentry capture because our exit hooks
        # mess with sentry's ability to send out errors before the program ends.
        sentry_exc(e, delay=True)
        raise_from(Exception("problem"), e)

    return run
