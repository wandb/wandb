import argparse
import os
import random
import sys
import time

import numpy as np
import wandb

parser = argparse.ArgumentParser()
parser.add_argument("--epochs", type=int, default=2)
parser.add_argument("--heavy", action="store_true", default=False)
parser.add_argument("--sleep_every", type=int, default=0)
args = parser.parse_args()
print("Calling init with args: {}", format(args))
print(
    "Environ: {}".format({k: v for k, v in os.environ.items() if k.startswith("WANDB")})
)
wandb.init(config=args, project="test")
print(f"Init called with config {wandb.config}")

# raise ValueError()
# os.kill(os.getpid(), signal.SIGINT)
for i in range(0, wandb.config.epochs):
    loss = random.uniform(0, wandb.config.epochs - i)
    print("loss: %s" % loss)
    wandb.log({"loss": loss}, commit=False)
    if wandb.config.heavy:
        for x in range(50):
            wandb.log(
                {f"hist_{x}": wandb.Histogram(np.random.randint(255, size=(1000)))},
                commit=False,
            )
    wandb.log({"cool": True})
    if wandb.config.sleep_every > 0 and i % wandb.config.sleep_every == 0:
        print("sleeping")
        time.sleep(random.random() + 1)
    sys.stdout.flush()
print("Finished")
