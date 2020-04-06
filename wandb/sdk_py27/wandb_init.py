# -*- coding: utf-8 -*-
"""
init.
"""

from __future__ import print_function

import wandb
from .wandb_run import Run
from wandb.util.globals import set_global
from wandb.backend.backend import Backend
from wandb.stuff import util2
from wandb.util import reporting

import time
import json
import atexit
import six
import logging
from six import raise_from
from wandb.stuff import io_wrap
import sys
import os
from wandb.util import redirect

from .wandb_settings import Settings

if wandb.TYPE_CHECKING:
    from typing import Optional, Union, List, Dict, Any  # noqa: F401

logger = logging.getLogger("wandb")


def online_status(*args, **kwargs):
    pass


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

    #read_fd, write_fd = win32pipe.FdCreatePipe(sa, 0, os.O_TEXT)
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

        self._atexit_cleanup_called = None

    def setup(self, kwargs):
        self.kwargs = kwargs

        wl = wandb.setup()
        settings = wl.settings(
            dict(kwargs.pop("settings", None) or tuple()))

        self._reporter = reporting.setup_reporter(
            settings=settings.duplicate().freeze())

        # Remove parameters that are not part of settings
        self.config = kwargs.pop("config", None)

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
                self._reporter.warning("unsupported wandb.init() arg: %s", key)

        settings.apply_init(kwargs)

        # TODO(jhr): should this be moved? probably.
        d = dict(start_time=time.time())
        settings.update(d)

        self.wl = wl
        self.settings = settings.freeze()

    def _atexit_cleanup(self):
        if self._atexit_cleanup_called:
            return
        self._atexit_cleanup_called = True

        ret = self.backend.interface.send_exit_sync(0, timeout=60)
        logger.info("got exit ret: %s", ret)

        self._restore()

        self.backend.cleanup()
        # FIXME: no warning allowed
        if self.run:
            self.run.on_finish()

    def _callback(self, name, data):
        logger.info("callback: %s, %s", name, data)
        self.backend.interface.send_output(name, data)

    def _redirect(self, stdout_slave_fd, stderr_slave_fd):
        console = self.settings.console
        logger.info("redirect: %s", console)

        if console == 'redirect':
            logger.info("redirect1")
            out_cap = redirect.Capture(name="stdout", cb=self._redirect_cb)
            out_redir = redirect.Redirect(src="stdout",
                                          dest=out_cap,
                                          unbuffered=True,
                                          tee=True)
            err_cap = redirect.Capture(name="stderr", cb=self._redirect_cb)
            err_redir = redirect.Redirect(src="stderr",
                                          dest=err_cap,
                                          unbuffered=True,
                                          tee=True)
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
            stdout_slave = os.fdopen(stdout_slave_fd, 'wb')
            stderr_slave = os.fdopen(stderr_slave_fd, 'wb')
            stdout_redirector = io_wrap.FileRedirector(sys.stdout,
                                                       stdout_slave)
            stderr_redirector = io_wrap.FileRedirector(sys.stderr,
                                                       stderr_slave)
            stdout_redirector.redirect()
            stderr_redirector.redirect()
            self.stdout_redirector = stdout_redirector
            self.stderr_redirector = stderr_redirector
        logger.info("redirect done")

    def _restore(self):
        logger.info("restore")
        # FIXME(jhr): drain and shutdown all threads
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
        wl = self.wl
        config = self.config

        data = ""
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                data = f.read()
            print("got data", data)
            c = json.loads(data)
            for k, v in c.items():
                config[k] = v

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

        if console == 'redirect':
            pass
        elif console == 'off':
            pass
        elif console == 'mock':
            pass
        elif console == 'file':
            pass
        elif console == 'iowrap':
            stdout_master_fd, stdout_slave_fd = io_wrap.wandb_pty(resize=False)
            stderr_master_fd, stderr_slave_fd = io_wrap.wandb_pty(resize=False)
        elif console == '_win32':
            # Not used right now
            stdout_master_fd, stdout_slave_fd = win32_create_pipe()
            stderr_master_fd, stderr_slave_fd = win32_create_pipe()
        else:
            self._reporter.internal("Unknown console: %s", console)

        backend = Backend(mode=s.mode)
        backend.ensure_launched(
            settings=s,
            log_fname=wl._log_internal_filename,
            data_fname=wl._data_filename,
            stdout_fd=stdout_master_fd,
            stderr_fd=stderr_master_fd,
            use_redirect=self._use_redirect,
        )
        backend.server_connect()

        # resuming needs access to the server, check server_status()?

        run = Run(config=config, settings=s)
        run._set_backend(backend)
        run._set_reporter(self._reporter)
        # TODO: pass mode to backend
        run_synced = None

        backend._hack_set_run(run)

        if s.mode == 'online':
            ret = backend.interface.send_run_sync(run, timeout=30)
            # TODO: fail on error, check return type
            run._set_run_obj(ret.run)
        elif s.mode in ('offline', 'dryrun'):
            backend.interface.send_run(run)
        elif s.mode in ('async', 'run'):
            try:
                err = backend.interface.send_run_sync(run, timeout=10)
            except Backend.Timeout:
                pass
            # TODO: on network error, do async run save
            backend.interface.send_run(run)

        self.run = run
        self.backend = backend
        set_global(run=run, config=run.config, log=run.log, join=run.join)
        self._reporter.set_context(run=run)
        run.on_start()

        logger.info("atexit reg")
        atexit.register(lambda: self._atexit_cleanup())

        if self._use_redirect:
            # setup fake callback
            self._redirect_cb = self._callback

        self._redirect(stdout_slave_fd, stderr_slave_fd)

        # for super agent
        run._save_job_spec()

        return run


def getcaller():
    src, line, func, stack = logger.findCaller(stack_info=True)
    print("Problem at:", src, line, func)


def init(
        settings = None,
        entity = None,
        team = None,
        project = None,
        mode = None,
        group = None,
        job_type = None,
        tags = None,
        name = None,
        config = None,  # TODO(jhr): type is a union for argparse/absl
        notes = None,
        magic = None,  # FIXME: type is union
        config_exclude_keys=None,
        config_include_keys=None,
        reinit = None,
        anonymous = None,
        dir=None,
        allow_val_change=None,
        resume=None,
        force=None,
        tensorboard=None,
        sync_tensorboard=None,
        monitor_gym=None,
        id=None,
):
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
    kwargs = locals()
    try:
        wi = _WandbInit()
        wi.setup(kwargs)
        try:
            run = wi.init()
        except (KeyboardInterrupt, Exception) as e:
            getcaller()
            logger.exception("we got issues")
            wi._atexit_cleanup()
            if wi.settings.problem == "fatal":
                raise
            if wi.settings.problem == "warn":
                pass
            return None
    except KeyboardInterrupt as e:
        logger.warning("interupted", exc_info=e)
        raise_from(Exception("interrupted"), e)
    except Exception as e:
        logger.error("error", exc_info=e)
        raise_from(Exception("problem"), e)

    return run
