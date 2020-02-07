"""
init.
"""

from wandb.wandb_run import Run
from wandb.util.globals import set_global
from wandb.internal.backend import Backend
import wandb
import click

import typing
if typing.TYPE_CHECKING:
    from typing import Dict, List, Optional


# priority order (highest to lowest):
# WANDB_FORCE_MODE
# settings.force_mode
# wandb.init(mode=)
# WANDB_MODE
# settings.mode

def init(
        settings=None,
        mode=None,      # type: int
        entity=None,
        team=None,
        project=None,
        magic=None,
        config=None,
        reinit=None,
        name=None,
        group=None
        ):
    # type: (...) -> Optional[Run]
    if mode == "noop":
        return None
    if mode == "test":
        return None

    backend = Backend(mode=mode)
    backend.ensure_launched()
    backend.server_connect()

    # resuming needs access to the server, check server_status()?

    run = Run(config=config, _backend=backend)

    settings=dict(entity="jeff", project="uncategorized")

    emojis = dict(star="⭐️", broom="🧹", rocket="🚀")
    url = "https://app.wandb.test/{}/{}/runs/{}".format(
        settings.get("entity"),
        settings.get("project"),
        run.run_id)
    wandb.termlog("{} View run at {}".format(
        emojis.get("rocket", ""),
        click.style(url, underline=True, fg='blue')))

    backend.run_update(dict(run_id=run.run_id, config=run.config._as_dict()))
    set_global(run=run, config=run.config, log=run.log, join=run.join)
    return run
