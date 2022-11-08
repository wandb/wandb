#!/usr/bin/env python3
import wandb


if __name__ == "__main__":
    run = wandb.init(project="pex")
    run.log({"test": 1})
    run.finish()
