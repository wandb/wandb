#!/usr/bin/env python
import sys
import time
import tqdm
import wandb

run = wandb.init()
wandb.log(dict(this=2))
print("before emoji")
for i in range(100):
    print(f"line-{i}-😃")
print("after emoji", file=sys.stderr)
