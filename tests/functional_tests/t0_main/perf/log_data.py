#!/usr/bin/env python
import argparse

import wandb
import yea


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-epochs", type=int, default=10)
    parser.add_argument("--num-scalers", type=int, default=10)
    args = parser.parse_args()

    run = wandb.init()
    for i in range(args.num_epochs):
        data = {}
        for j in range(args.num_scalers):
            data[f"m-{j}"] = j * i
        wandb.log(data)
    run.finish()


if __name__ == "__main__":
    yea.setup()
    main()
