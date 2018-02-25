import argparse
import time
import random
import wandb
import os
import signal

parser = argparse.ArgumentParser()
parser.add_argument('--epochs', type=int, default=2)
args = parser.parse_args()

run = wandb.init(config=args)

#raise ValueError()
#os.kill(os.getpid(), signal.SIGINT)
for i in range(0, run.config.epochs):
    loss = random.uniform(0, run.config.epochs - i)
    print("loss: %s" % loss)
    run.history.add({"loss": loss})

print("Finished")
