#
import wandb

from . import preinit


def set_global(
    run=None,
    config=None,
    log=None,
    summary=None,
    save=None,
    use_artifact=None,
    log_artifact=None,
    define_metric=None,
    alert=None,
    mark_preempting=None,
    log_model=None,
    use_model=None,
    link_model=None,
    watch=None,
    unwatch=None,
):
    if run:
        wandb.run = run
    if config is not None:
        wandb.config = config
    if log:
        wandb.log = log
    if summary is not None:
        wandb.summary = summary
    if save:
        wandb.save = save
    if use_artifact:
        wandb.use_artifact = use_artifact
    if log_artifact:
        wandb.log_artifact = log_artifact
    if define_metric:
        wandb.define_metric = define_metric
    if alert:
        wandb.alert = alert
    if mark_preempting:
        wandb.mark_preempting = mark_preempting
    if log_model:
        wandb.log_model = log_model
    if use_model:
        wandb.use_model = use_model
    if link_model:
        wandb.link_model = link_model
    if watch:
        wandb.watch = watch
    if unwatch:
        wandb.unwatch = unwatch


def unset_globals():
    wandb.run = None
    wandb.config = preinit.PreInitObject("wandb.config")
    wandb.summary = preinit.PreInitObject("wandb.summary")
    wandb.log = preinit.PreInitCallable("wandb.log", wandb.Run.log)
    wandb.watch = preinit.PreInitCallable("wandb.watch", wandb.Run.watch)
    wandb.unwatch = preinit.PreInitCallable("wandb.unwatch", wandb.Run.unwatch)
    wandb.save = preinit.PreInitCallable("wandb.save", wandb.Run.save)
    wandb.use_artifact = preinit.PreInitCallable(
        "wandb.use_artifact", wandb.Run.use_artifact
    )
    wandb.log_artifact = preinit.PreInitCallable(
        "wandb.log_artifact", wandb.Run.log_artifact
    )
    wandb.define_metric = preinit.PreInitCallable(
        "wandb.define_metric", wandb.Run.define_metric
    )
