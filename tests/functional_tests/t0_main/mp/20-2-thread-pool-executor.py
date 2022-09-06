#!/usr/bin/env python
"""Simple example of using ThreadPoolExecutor with service.
    This example is base on issue https://wandb.atlassian.net/browse/WB-8733
"""
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor

import wandb
import yea


def worker(initial: int):
    with wandb.init(project="tester222", config={"init": initial}) as run:
        for i in range(3):
            run.log({"i": initial + i})


def main():
    mp.set_start_method("spawn")
    wandb.require("service")
    with ThreadPoolExecutor(max_workers=4) as e:
        e.map(worker, [12, 2, 40, 17])


if __name__ == "__main__":
    yea.setup()
    main()
