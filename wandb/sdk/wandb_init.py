# -*- coding: utf-8 -*-
"""
init.
"""

from prompt_toolkit import prompt  # type: ignore
import wandb
from .wandb_run import Run
from wandb.util.globals import set_global
# from wandb.internal.backend_grpc import Backend
from wandb.internal.backend_mp import Backend
from wandb.stuff import util2

import platform
import six
import getpass
import logging
from six import raise_from
from wandb.stuff import io_wrap
import sys
import os

from wandb.apis import internal

# import typing
# if typing.TYPE_CHECKING:
#   from typing import Dict, List, Optional
# from typing import Optional, Dict
from typing import Optional, Dict  # noqa: F401

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

def _get_python_type():
    try:
        if 'terminal' in get_ipython().__module__:
            return 'ipython'
        else:
            return 'jupyter'
    except (NameError, AttributeError):
        return "python"


def win32_redirect(stdout_slave_fd, stderr_slave_fd):
    import win32api

    # save for later
    fd_stdout = os.dup(1)
    fd_stderr = os.dup(2)

    std_out = win32api.GetStdHandle(win32api.STD_OUTPUT_HANDLE)
    std_err = win32api.GetStdHandle(win32api.STD_ERROR_HANDLE)

    os.dup2(stdout_slave_fd, 1)
    os.dup2(stderr_slave_fd, 2)

    # TODO(jhr): do something about current stdout, stderr file handles


def win32_create_pipe():
    import pywintypes
    import win32pipe

    sa=pywintypes.SECURITY_ATTRIBUTES()
    sa.bInheritHandle=0

    read_fd, write_fd = win32pipe.FdCreatePipe(sa, 0, os.O_TEXT)
    # http://timgolden.me.uk/pywin32-docs/win32pipe__FdCreatePipe_meth.html
    # https://stackoverflow.com/questions/17942874/stdout-redirection-with-ctypes
    return read_fd, write_fd


class _WandbInit(object):
    def __init__(self):
        self.kwargs = None
        self.settings = None
        self.config = None
        self.magic = None
        self.wl = None

    def setup(self, kwargs):
        self.kwargs = kwargs

        settings = kwargs.pop("settings", None)
        self.config = kwargs.pop("config", None)
        self.magic = kwargs.pop("magic", None)

        wl = wandb.setup()
        settings = settings or dict()
        s = wl.settings(**settings)
        d = dict(**kwargs)
        # strip out items where value is None
        d = {k: v for k, v in six.iteritems(d) if v is not None}
        s.update(d)
        s.freeze()
        self.wl = wl
        self.settings = s

    def init(self):
        s = self.settings
        wl = self.wl
        config = self.config

        if s.mode == "noop":
            return None

        api = internal.Api(default_settings=dict(s))
        if not api.api_key:
            in_jupyter = _get_python_type() != "python"
            if in_jupyter:
                app_url = s.base_url.replace("//api.", "//app.")
                print("Go to this URL in a browser: {}/authorize\n".format(app_url))
                key = getpass.getpass("Enter your authorization code:\n")
            else:
                key = prompt('Enter api key: ', is_password=True)
            util2.set_api_key(api, key)

        if platform.system() == "Windows":
            # create win32 pipes
            stdout_master_fd, stdout_slave_fd = win32_create_pipe()
            stderr_master_fd, stderr_slave_fd = win32_create_pipe()
        else:
            stdout_master_fd, stdout_slave_fd = io_wrap.wandb_pty(resize=False)
            stderr_master_fd, stderr_slave_fd = io_wrap.wandb_pty(resize=False)

        backend = Backend(mode=s.mode)
        backend.ensure_launched(settings=s,
                                log_fname=wl._log_internal_filename,
                                data_fname=wl._data_filename,
                                stdout_fd=stdout_master_fd,
                                stderr_fd=stderr_master_fd,
                                )
        backend.server_connect()

        # resuming needs access to the server, check server_status()?

        run = Run(config=config, settings=s)
        run._set_backend(backend)
        # TODO: pass mode to backend
        run_synced = None

        r = dict(run_id=run.run_id, config=run.config._as_dict(), project=s.project)
        if s.mode == 'online':
            ret = backend.send_run_sync(r, timeout=30)
            # TODO: fail on error, check return type
            run._set_run_obj(ret.run)
        elif s.mode in ('offline', 'dryrun'):
            backend.send_run(r)
        elif s.mode in ('async', 'run'):
            try:
                err = backend.send_run_sync(r, timeout=10)
            except Backend.Timeout:
                pass
            # TODO: on network error, do async run save
            backend.send_run(r)

        set_global(run=run, config=run.config, log=run.log, join=run.join)
        run.on_start()

        # redirect stdout
        if platform.system() == "Windows":
            win32_redirect(stdout_slave_fd, stderr_slave_fd)
        else:
            stdout_slave = os.fdopen(stdout_slave_fd, 'wb')
            stderr_slave = os.fdopen(stderr_slave_fd, 'wb')
            stdout_redirector = io_wrap.FileRedirector(sys.stdout, stdout_slave)
            stderr_redirector = io_wrap.FileRedirector(sys.stderr, stderr_slave)
            stdout_redirector.redirect()
            stderr_redirector.redirect()

        return run


def getcaller():
    src, line, func, stack = logger.findCaller(stack_info=True)
    print("Problem at:", src, line, func)


def init(
        settings: Dict = None,
        mode: str = None,
        entity: str = None,
        team: str = None,
        project: str = None,
        group: str = None,
        magic: bool = None,  # FIXME: type is union
        config: Dict = None,
        reinit: bool = None,
        anonymous: bool = None,
        name=None,
) -> Optional[Run]:
    """This is my comment.

    Intialize stuff.

    Args:
        settings: This is my setting.
        mode: set my mode.

    Raises:
        Exception

    Returns:
        The return value
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
    except KeyboardInterrupt:
        print("interrupt")
        raise_from(Exception("interrupted"), None)
    except Exception as e:
        print("got e", e)
        raise_from(Exception("problem"), None)

    return run
