import wandb


def set_global(run=None, config=None, log=None, join=None):
    if run:
        wandb.run = run
    if config:
        wandb.config = config
    if log:
        wandb.log = log
    if join:
        wandb.join = join
