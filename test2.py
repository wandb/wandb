import wandb
import numpy as np


with wandb.init(project="test_summary") as run:
  run.log({'Check': 0.1})
  run.log({'Loss': np.arange(100)})
  run.log({'Check2': [1,2,3,4]})
api = wandb.Api()
runs = list(api.runs("test_summary"))
run = runs[0]
