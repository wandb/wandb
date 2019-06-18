import argparse
import time
import random
import wandb
import os
import signal

parser = argparse.ArgumentParser()
parser.add_argument('--epochs', type=int, default=2)
args = parser.parse_args()

wandb.init(config=args)

#raise ValueError()
#os.kill(os.getpid(), signal.SIGINT)
for i in range(0, wandb.config.epochs):
    loss = random.uniform(0, wandb.config.epochs - i)
    print("loss: %s" % loss)
    wandb.log({"loss": loss}, commit=False)
    wandb.log({"cool": True})

print("Finished")
