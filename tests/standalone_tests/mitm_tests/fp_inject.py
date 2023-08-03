#!/usr/bin/env python
import time

import wandb
import yea


def main():
    run = wandb.init()
    history = 200
    for i in range(history):
        print(i)
        run.log(dict(num=i))
        time.sleep(0.1)
    print("done")
    run.finish()

    with open(run.settings.log_internal) as f:
        print(f.read())


if __name__ == "__main__":
    yea.setup()
    main()
