# -*- coding: utf-8 -*-
"""
init.
"""

from prompt_toolkit import prompt  # type: ignore
import wandb
from wandb.wandb_run import Run
from wandb.util.globals import set_global
# from wandb.internal.backend_grpc import Backend
from wandb.internal.backend_mp import Backend
import click
from wandb.stuff import util2

import six

from wandb.apis import internal

# import typing
# if typing.TYPE_CHECKING:
#   from typing import Dict, List, Optional
# from typing import Optional, Dict
import typing
if typing.TYPE_CHECKING:
    from typing import Optional, Dict  # noqa: F401

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


def init(
    settings=None,  # type: Dict
    mode=None,
    entity=None,
    team=None,
    project=None,
    group=None,
    magic=None,
    config=None,
    reinit=None,
    name=None,
):
    # type: (...) -> Optional[Run]
    """This is my comment.

    Intialize stuff.

    Args:
        settings: This is my setting.
        mode: set my mode.

    Returns:
        The return value
    """
    r = _init(locals())
    return r

def _init(self, **kwargs):
    settings = kwargs.pop("settings", None)
    config = kwargs.pop("config", None)

    wl = wandb.setup()
    settings = settings or dict()
    s = wl.settings(**settings)
    d = dict(**kwargs)
    # strip out items where value is None
    d = {k: v for k, v in six.iteritems(d) if v is not None}
    s.update(d)
    s.freeze()

    if s.mode == "noop":
        return None

    api = internal.Api(default_settings=dict(s))
    if not api.api_key:
        key = prompt('Enter api key: ', is_password=True)
        util2.set_api_key(api, key)

    backend = Backend(mode=s.mode)
    backend.ensure_launched(log_fname=wl._log_internal_filename)
    backend.server_connect()

    # resuming needs access to the server, check server_status()?

    run = Run(config=config)
    run._set_backend(backend)

    emojis = dict(star="⭐️", broom="🧹", rocket="🚀")
    url = "{}/{}/{}/runs/{}".format(
        s.base_url, s.team, s.project, run.run_id)
    wandb.termlog("{} View run at {}".format(
        emojis.get("rocket", ""), click.style(url, underline=True, fg='blue')))

    backend.run_update(dict(run_id=run.run_id, config=run.config._as_dict()))
    set_global(run=run, config=run.config, log=run.log, join=run.join)
    return run
