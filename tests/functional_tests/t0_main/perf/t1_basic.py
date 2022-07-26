#!/usr/bin/env python
import sys
import time


def main():
    import wandb

    run = wandb.init()
    wandb.log(dict(this=2))
    wandb.finish()


if __name__ == "__main__":
    import yea

    yea.setup()

    main()
