import wandb
from wandb.lib import preinit


def set_global(
    run=None,
    config=None,
    log=None,
    summary=None,
    save=None,
    restore=None,
    use_artifact=None,
    log_artifact=None,
):
    if run:
        wandb.run = run
    if config:
        wandb.config = config
    if log:
        wandb.log = log
    if summary:
        wandb.summary = summary
    if save:
        wandb.save = save
    if restore:
        wandb.restore = restore
    if use_artifact:
        wandb.use_artifact = use_artifact
    if log_artifact:
        wandb.log_artifact = log_artifact


def unset_globals():
    wandb.run = None
    wandb.config = preinit.PreInitObject("wandb.config")
    wandb.summary = preinit.PreInitObject("wandb.summary")
    wandb.log = preinit.PreInitCallable(
        "wandb.log", wandb.wandb_sdk.wandb_run.Run.log
    )
    wandb.save = preinit.PreInitCallable(
        "wandb.save", wandb.wandb_sdk.wandb_run.Run.save
    )
    wandb.restore = preinit.PreInitCallable(
        "wandb.restore", wandb.wandb_sdk.wandb_run.Run.restore
    )
    wandb.use_artifact = preinit.PreInitCallable(
        "wandb.use_artifact", wandb.wandb_sdk.wandb_run.Run.use_artifact
    )
    wandb.log_artifact = preinit.PreInitCallable(
        "wandb.log_artifact", wandb.wandb_sdk.wandb_run.Run.log_artifact
    )
