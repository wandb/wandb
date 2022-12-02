#!/usr/bin/env python
import time

import wandb
from relay_link import RelayLink

rl = RelayLink()

rl.delay("graphql", 20)
run = wandb.init()

history = 20

for i in range(history):
    if i % 10 == 0:
        print(i)

    run.log(dict(num=i))
    time.sleep(0.1)

    if i == 10:
        rl.pause("filestream")

rl.unpause("graphql")

print("done")
run.finish()
