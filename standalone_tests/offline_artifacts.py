import wandb
from wandb.cli import cli
import numpy as np

project = "offline_artifacts_test"

run = wandb.init(project=project, mode="offline")
dataset = wandb.Table(data=[
    [str(i), wandb.Image(np.random.randint(255, size=(32,32)))]
    for i in range(250)
], columns=["id", "input_image"])
run.log({"dataset": dataset})
run.finish()

print("PRE SYNC")

print(dir(cli.sync))
