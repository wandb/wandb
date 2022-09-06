import shutil

import wandb

wandb.require("service")

# Triggers a FileNotFoundError from the internal process
# because the internal process reads/writes to the current run directory.
run = wandb.init()
shutil.rmtree(run.dir)
run.log({"data": 5})
