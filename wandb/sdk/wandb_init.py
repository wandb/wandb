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

import time
import json
import atexit
import platform
import six
import logging
from six import raise_from
from wandb.stuff import io_wrap
import sys
import os
from wandb.util import redirect

# from wandb.apis import internal

# import typing
# if typing.TYPE_CHECKING:
#   from typing import Dict, List, Optional
# from typing import Optional, Dict
from typing import Optional, Union, List, Dict  # noqa: F401

logger = logging.getLogger("wandb")

# priority order (highest to lowest):
# WANDB_FORCE_MODE
# settings.force_mode
# wandb.init(mode=)
# WANDB_MODE
# settings.mode
# ) -> Optional[Run]:

# def init(settings: Dict = None,
#          mode: int = None,
#          entity=None,
#          team=None,
#          project=None,
#          group=None,
#          magic=None,
#          config=None,
#          reinit=None,
#          name=None,
#          ) -> Optional[Run]:


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

        # move this
        self.stdout_redirector = None
        self.stderr_redirector = None
        self._save_stdout = None
        self._save_stderr = None

    def setup(self, kwargs):
        self.kwargs = kwargs

        settings = kwargs.pop("settings", None)

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
                logger.info("unsupported wandb.init() arg: %s", val)

        wl = wandb.setup()
        settings = settings or dict()
        s = wl.settings(**settings)
        d = dict(**kwargs)
        # strip out items where value is None
        d = {k: v for k, v in six.iteritems(d) if v is not None}

        # TODO(jhr): should this be moved? probably.
        d.setdefault("start_time", time.time())

        s.update(d)
        s.freeze()
        self.wl = wl
        self.settings = s

    def _atexit_cleanup(self):

        ret = self.backend.interface.send_exit_sync(0, timeout=30)
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
        logger.info("redirect")

        if self._use_redirect:
            out = False
            err = False
            out = True
            err = True
            if out:
                out_cap = redirect.Capture(name="stdout", cb=self._redirect_cb)
                out_redir = redirect.Redirect(src="stdout",
                                              dest=out_cap,
                                              unbuffered=True,
                                              tee=True)
            if err:
                err_cap = redirect.Capture(name="stderr", cb=self._redirect_cb)
                err_redir = redirect.Redirect(src="stderr",
                                              dest=err_cap,
                                              unbuffered=True,
                                              tee=True)
            if out:
                out_redir.install()
            if err:
                err_redir.install()
            if out:
                self._out_redir = out_redir
            if err:
                self._err_redir = err_redir
            logger.info("redirect2")
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
            return None

        # Make sure we are logged in
        wandb.login()

        if self._use_redirect:
            stdout_master_fd = None
            stderr_master_fd = None
            stdout_slave_fd = None
            stderr_slave_fd = None
            #self._redirect_q = self.wl._multiprocessing.Queue()
        else:
            if platform.system() == "Windows":
                # create win32 pipes
                stdout_master_fd, stdout_slave_fd = win32_create_pipe()
                stderr_master_fd, stderr_slave_fd = win32_create_pipe()
            else:
                stdout_master_fd, stdout_slave_fd = io_wrap.wandb_pty(
                    resize=False)
                stderr_master_fd, stderr_slave_fd = io_wrap.wandb_pty(
                    resize=False)

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
        # TODO: pass mode to backend
        run_synced = None

        backend._hack_set_run(run)

        run_config = run.config._as_dict()
        logger.info("runconfig: %s", run_config)
        r = dict(run_id=run.run_id, config=run_config, project=s.project)
        if s.mode == 'online':
            ret = backend.interface.send_run_sync(r, timeout=30)
            # TODO: fail on error, check return type
            run._set_run_obj(ret.run)
        elif s.mode in ('offline', 'dryrun'):
            backend.interface.send_run(r)
        elif s.mode in ('async', 'run'):
            try:
                err = backend.interface.send_run_sync(r, timeout=10)
            except Backend.Timeout:
                pass
            # TODO: on network error, do async run save
            backend.interface.send_run(r)

        self.run = run
        self.backend = backend
        set_global(run=run, config=run.config, log=run.log, join=run.join)
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
        entity: Optional[str] = None,
        team: Optional[str] = None,
        project: Optional[str] = None,
        settings: Optional[Dict] = None,
        mode: Optional[str] = None,
        group: Optional[str] = None,
        job_type: Optional[str] = None,
        tags: Optional[List] = None,
        name: Optional[str] = None,
        config: Union[
            Dict, None] = None,  # TODO(jhr): type is a union for argparse/absl
        notes: Optional[str] = None,
        magic: bool = None,  # FIXME: type is union
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
) -> Optional[Run]:
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
            if wi.settings.problem == "fatal":
                raise
            if wi.settings.problem == "warn":
                pass
            # silent or warn
            # TODO: return dummy run instead
            return None
    except KeyboardInterrupt as e:
        logger.warning("interupted", exc_info=e)
        raise_from(Exception("interrupted"), e)
    except Exception as e:
        logger.error("error", exc_info=e)
        raise_from(Exception("problem"), e)

    return run
