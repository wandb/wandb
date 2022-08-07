import multiprocessing

import wandb


def mp_func():
    """This needs to be defined at the module level to be picklable and sendable to
    the spawned process via multiprocessing"""
    print("hello from the other side")


def main():
    wandb.init()
    context = multiprocessing.get_context("spawn")
    p = context.Process(target=mp_func)
    p.start()
    p.join()
    wandb.finish()
