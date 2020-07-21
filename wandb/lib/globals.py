import wandb
from wandb.lib import preinit


def set_global(run=None, config=None, log=None, join=None, summary=None):
    if run:
        wandb.run = run
    if config:
        wandb.config = config
    if log:
        wandb.log = log
    if join:
        wandb.join = join
    if summary:
        wandb.summary = summary


def unset_globals():
    wandb.run = None
    wandb.config = preinit.PreInitObject("wandb.config")
    wandb.summary = preinit.PreInitObject("wandb.summary")
    wandb.log = preinit.PreInitCallable("wandb.log")
    wandb.join = preinit.PreInitCallable("wandb.join")
