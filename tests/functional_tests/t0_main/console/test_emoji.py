#!/usr/bin/env python
import sys

import wandb

run = wandb.init()
wandb.log(dict(this=2))
print("before emoji")
for i in range(100):
    print(f"line-{i}-\N{grinning face}")
print("after emoji", file=sys.stderr)
