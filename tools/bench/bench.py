#!/usr/bin/env python
from __future__ import annotations

import argparse
import multiprocessing

import _load_profiles
import _timing
import numpy
import wandb

VERSION: str = "v1-2024-04-11-0"
BENCH_OUTFILE: str = "bench.csv"
BENCH_FIELDS: tuple[str] = (
    "test_name",
    "test_profile",
    "test_variant",
    "client_version",
    "client_type",
    "server_version",
    "server_type",
)
TIMING_DATA: list = []


def run_one(args, n=0, m=0):
    with wandb.init(mode=args.mode) as run:
        for e in range(args.num_history):
            d = {}
            for i in range(args.history_floats):
                d[f"f_{i}"] = float(n + m + e + i)
            for i in range(args.history_ints):
                d[f"n_{i}"] = n + m + e + i
            for i in range(args.history_strings):
                d[f"s_{i}"] = str(n + m + e + i)
            for i in range(args.history_tables):
                d[f"t_{i}"] = wandb.Table(
                    columns=["a", "b", "c", "d"], data=[[n + m, e, i, i + 1]]
                )
            for i in range(args.history_images):
                d[f"i_{i}"] = wandb.Image(
                    numpy.random.randint(
                        255,
                        size=(args.history_images_dim, args.history_images_dim, 3),
                        dtype=numpy.uint8,
                    )
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


def teardown(args):
    wandb.teardown()


@_timing.timeit(TIMING_DATA)
def time_load(args):
    if args.num_parallel > 1:
        run_parallel(args)
    else:
        run_sequential(args)


def run_load(args):
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
    parser.add_argument("--client_version", type=str, default=wandb.__version__)
    parser.add_argument("--client_type", type=str, default="")
    parser.add_argument("--num_sequential", type=int, default=1)
    parser.add_argument("--num_parallel", type=int, default=1)
    parser.add_argument("--num_history", type=int, default=1)
    parser.add_argument("--history_floats", type=int, default=0)
    parser.add_argument("--history_ints", type=int, default=0)
    parser.add_argument("--history_strings", type=int, default=0)
    parser.add_argument("--history_tables", type=int, default=0)
    parser.add_argument("--history_images", type=int, default=0)
    parser.add_argument("--history_images_dim", type=int, default=16)
    parser.add_argument(
        "--mode", type=str, default="online", choices=("online", "offline")
    )
    parser.add_argument("--use-spawn", action="store_true")

    args = parser.parse_args()

    # required by golang experimental client when testing multiprocessing workloads
    if args.use_spawn:
        multiprocessing.set_start_method("spawn")

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
        _timing.write(BENCH_OUTFILE, TIMING_DATA, prefix_list=prefix_list)


if __name__ == "__main__":
    main()
