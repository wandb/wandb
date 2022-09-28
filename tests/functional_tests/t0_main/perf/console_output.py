#!/usr/bin/env python
import argparse
import sys

import wandb
import yea


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-total", type=int, default=10)
    parser.add_argument("--output-chunk", type=int, default=10)
    args = parser.parse_args()

    run = wandb.init()
    for i in range(args.output_total):
        for _ in range(args.output_chunk):
            sys.stdout.write(".")
        sys.stdout.write(f"{i}\r")
    sys.stdout.write("\n")
    run.finish()


if __name__ == "__main__":
    yea.setup()
    main()
