import wandb

run = wandb.init()

for x in range(10):
    run.log(dict(a=x))
