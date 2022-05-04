import multiprocessing as mp

import wandb


def child_process(run):
    run.finish()


if __name__ == "__main__":
    wandb.require("service")

    with wandb.init() as run:
        p = mp.Process(target=child_process, args=(run,))
        run.finish()
        p.start()
    p.join()
    run.finish()
