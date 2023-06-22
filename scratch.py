import wandb

run = wandb.init()
assert run
for i in range(100):
    run.log({"acc": 0.9, "loss": 0.2})
run.finish()
