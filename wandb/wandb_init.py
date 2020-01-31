"""
init.
"""

from wandb.wandb_run import Run
from wandb.util.globals import set_global
from wandb.internal.backend import Backend

# priority order (highest to lowest):
# WANDB_FORCE_MODE
# settings.force_mode
# wandb.init(mode=)
# WANDB_MODE
# settings.mode

def init(settings=None, mode=None, entity=None, team=None, project=None, magic=None, config=None, reinit=None, name=None, group=None):
    if mode == "noop":
        return
    if mode == "test":
        return

    backend = Backend(mode=mode)
    backend.ensure_launched()
    backend.server_connect()

    # resuming needs access to the server, check server_status()?

    run = Run(config=config, _backend=backend)
    set_global(run=run, config=run.config, log=run.log, join=run.join)
    return run
