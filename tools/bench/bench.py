#!/usr/bin/env python

import argparse
import multiprocessing
import os
from typing import List, Tuple

import _load_profiles
import _timing
import wandb

VERSION: str = "v1-2024-04-11-0"
BENCH_OUTFILE: str = "bench.csv"
BENCH_FIELDS: Tuple[str] = (
    "test_name",
    "test_profile",
    "test_variant",
    "client_version",
    "client_type",
    "server_version",
    "server_type",
)
TIMING_DATA: List = []


def run_one(args, n=0, m=0):
    with wandb.init(mode=args.mode) as run:
        for e in range(args.num_history):
            d = {}
            for i in range(args.history_floats):
                d[f"f_{i}"] = float(n + m + e + i)
            for i in range(args.history_ints):
                d[f"i_{i}"] = n + m + e + i
            for i in range(args.history_strings):
                d[f"s_{i}"] = str(n + m + e + i)
            for i in range(args.history_tables):
                d[f"t_{i}"] = wandb.Table(
                    columns=["a", "b", "c", "d"], data=[[n + m, e, i, i + 1]]
                )
            run.log(d)


def run_sequential(args, m=0):
    for n in range(args.num_sequential):
        run_one(args, n, m)


def run_parallel(args):
    procs = []
    wandb.setup()
    for n in range(args.num_parallel):
        p = multiprocessing.Process(
            target=run_sequential, args=(args, n * args.num_parallel)
        )
        procs.append(p)
    for p in procs:
        p.start()
    for p in procs:
        p.join()


def setup(args):
    # print("DEBUG SETUP", args)
    if args.core == "true":
        # print("REQ CORE")
        wandb.require("core")


def teardown(args):
    # print("DEBUG TEARDOWN")
    wandb.teardown()
    os.environ.pop("WANDB__REQUIRE_CORE", None)


@_timing.timeit(TIMING_DATA)
def time_load(args):
    if args.num_parallel > 1:
        run_parallel(args)
    else:
        run_sequential(args)


def run_load(args):
    setup(args)
    time_load(args)
    teardown(args)


def main():
    parser = argparse.ArgumentParser(description="benchmark wandb performance")
    parser.add_argument("--test_name", type=str, default="")
    parser.add_argument(
        "--test_profile", type=str, default="", choices=list(_load_profiles.PROFILES)
    )
    parser.add_argument("--test_variant", type=str, default="")
    parser.add_argument("--server_version", type=str, default="")
    parser.add_argument("--server_type", type=str, default="")
    parser.add_argument("--client_version", type=str, default="")
    parser.add_argument("--client_type", type=str, default="")
    parser.add_argument("--num_sequential", type=int, default=1)
    parser.add_argument("--num_parallel", type=int, default=1)
    parser.add_argument("--num_history", type=int, default=1)
    parser.add_argument("--history_floats", type=int, default=0)
    parser.add_argument("--history_ints", type=int, default=0)
    parser.add_argument("--history_strings", type=int, default=0)
    parser.add_argument("--history_tables", type=int, default=0)
    parser.add_argument("--mode", type=str, default="", choices=("online", "offline"))
    parser.add_argument("--core", type=str, default="", choices=("true", "false"))
    # parser.add_argument("--artifacts", type=int)
    # parser.add_argument("--artifact_files", type=int)

    args = parser.parse_args()
    args_list = []
    if args.test_profile:
        args_list = _load_profiles.parse_profile(parser, args, copy_fields=BENCH_FIELDS)
    else:
        args_list.append(args)

    for args in args_list:
        run_load(args)
        prefix_list = [VERSION]
        for field in BENCH_FIELDS:
            prefix_list.append(getattr(args, field))
        _timing.write(BENCH_OUTFILE, TIMING_DATA, prefix=prefix_list)


if __name__ == "__main__":
    main()
