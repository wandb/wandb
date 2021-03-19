#!/bin/bash
# from abc import abstractmethod, ABCMeta

if ! [ -x "$(command -v wandb)" ]; then
  echo 'W&B not installed, installing...'
  # TODO: replace this with the mainline
  pip install -qq --upgrade https://storage.googleapis.com/wandb/wandb-0.10.23.dev1-py2.py3-none-any.whl
fi

echo "W&B installed, be sure to set WANDB_API_KEY"
if ! [ -z "${WANDB_CODE_ARTIFACT}" ]; then
    wandb artifact get --root . $WANDB_CODE_ARTIFACT
fi



cat <<EOF > ./wandb-demo.py
import wandb
import random
import time
with wandb.init(project="ngc", config={"lr": 0.001, "dropout": 0.2, "epochs": 10, "layer_size": 32}) as run:
    loss = random.uniform(0, min(run.config.dropout * run.config.lr, 0.01))
    print("Learning Rate: {}, Dropout: {}, Target: {}".format(run.config.lr, run.config.dropout, loss))
    x = loss / run.config.epochs
    penalty = random.uniform(x, x * 4)
    for i in range(run.config.epochs):
        epoch_penalty = random.uniform(0, abs((run.config.epochs - (i + 1)) * penalty))
        wandb.log({"loss": loss + epoch_penalty, "val_loss": loss + epoch_penalty * random.uniform(0.5, 1.5)})
        time.sleep(1.0)
EOF