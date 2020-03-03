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

import six
import logging
from six import raise_from

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
            key = prompt('Enter api key: ', is_password=True)
            util2.set_api_key(api, key)

        backend = Backend(mode=s.mode)
        backend.ensure_launched(settings=s,
                                log_fname=wl._log_internal_filename,
                                data_fname=wl._data_filename,
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
        return run


def getcaller():
    src, line, func, stack = logger.findCaller(stack_info=True)
    print("Problem at:", src, line, func)


def init(
        settings = None,
        mode = None,
        entity = None,
        team = None,
        project = None,
        group = None,
        magic = None,  # FIXME: type is union
        config = None,
        reinit = None,
        name=None,
):
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
