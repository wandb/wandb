import sys
import time

import tqdm
import wandb

run = wandb.init()
wandb.log(dict(this=2))
print("before progress")
for outer in tqdm.tqdm([10, 20, 30, 40, 50], desc=" outer", position=0):
    for _inner in tqdm.tqdm(range(outer), desc=" inner loop", position=1, leave=False):
        time.sleep(0.05)
print("done!")
print("after progress", file=sys.stderr)
print("final progress")
