import wandb
wandb.init(mode="offline", config=dict(init1=11, init2=22))
wandb.config.extra3=33
wandb.log(dict(this="that"))
wandb.log(dict(yes=2))
