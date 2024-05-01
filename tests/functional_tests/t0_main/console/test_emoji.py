#!/usr/bin/env python
import sys

import wandb

run = wandb.init()
wandb.log(dict(this=2))
print("before emoji")
for i in range(100):
    print(f"line-{i}-\N{GRINNING FACE}")
print("after emoji", file=sys.stderr)
