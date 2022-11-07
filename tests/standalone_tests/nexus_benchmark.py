#!/usr/bin/env python

import os
import time
import multiprocessing as mp

import wandb


NUM_HISTORY = 10000
# NUM_HISTORY = 1000
NUM_WORKERS = 12
TIME_LIMIT = 240


def do_one(num):
    run = wandb.init()
    for _ in range(NUM_HISTORY):
        run.log(dict(a=1, b=4, c=5))
    run.finish()
    return num


def do_pool():
    num_proc = NUM_WORKERS
    pool = mp.Pool(processes=num_proc)
    result = pool.map_async(do_one, range(num_proc))
    data = result.get(TIME_LIMIT)
    assert len(data) == num_proc

def do_tests(testname):
    print("-" * 40)
    print(f"Running: {testname}")
    print("v" * 40)
    start = time.time()
    do_pool()
    end = time.time()
    total = end - start
    print("^" * 40)
    print(f"Elapsed: {total}")
    print("-" * 40)
    print("")
    return total


def perf_standard():
    wandb.setup(settings=wandb.Settings(_disable_stats=True, _disable_meta=True))
    total = do_tests("Standard")
    wandb.teardown()
    return total


def perf_nexus():
    os.environ["WBSERVICE"] = "/tmp/wandb-nexus"
    wandb.setup(settings=wandb.Settings(_disable_stats=True, _disable_meta=True))
    total = do_tests("Nexus")
    wandb.teardown()
    return total


def main():
    os.environ["WANDB_MODE"] = "offline"
    os.environ["WANDB__DISABLE_STATS"] = "true"
    os.environ["WANDB__DISABLE_META"] = "true"
    time_std = perf_standard()
    time_nex = perf_nexus()
    print(f"Test     | seconds")
    print("-" * 20)
    print(f"Standard | {time_std}")
    print(f"Nexus    | {time_nex}")
    print("")
    speed_up = (time_std / time_nex)
    print(f"Speed-up: {speed_up:.2f}x")


if __name__ == "__main__":
    main()
