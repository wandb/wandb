#!/usr/bin/env python

import argparse
from concurrent.futures import ThreadPoolExecutor

import wandb

wandb.setup()


def do_run():
    run = wandb.init()
    run.log({"a": 1, "b": 2, "c": 4.0, "d": "blah"})
    run.finish()


parser = argparse.ArgumentParser(description="benchmark wandb performance")
parser.add_argument("--num-workers", "-n", type=int, default=20)
args = parser.parse_args()

jobs = []
with ThreadPoolExecutor(max_workers=args.num_workers) as executor:
    for _ in range(args.num_workers):
        jobs.append(executor.submit(do_run))

for job in jobs:
    _ = job.result()
print("done")
