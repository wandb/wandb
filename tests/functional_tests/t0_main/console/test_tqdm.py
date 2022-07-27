#!/usr/bin/env python
import sys
import time

import tqdm
import wandb

run = wandb.init()
wandb.log(dict(this=2))
print("before progress")
for _ in tqdm.tqdm(range(100), ascii=" 123456789#"):
    time.sleep(0.1)
print("after progress", file=sys.stderr)
print("final progress")
