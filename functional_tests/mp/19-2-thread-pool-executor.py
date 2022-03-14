from concurrent.futures import ThreadPoolExecutor
from random import random
import wandb


def _log_():
    for i in range(5):
        # info = log_queue.get()
        info = {"a": i}
        print(f"Info from queue: {info}")
        wandb.log(info)  # this is getting stuck on the log process
        print("logged to wandb...")
        # log_queue.task_done()


if __name__ == "__main__":
    # log_queue = queue.Queue()
    wandb.require("service")
    run = wandb.init()
    with ThreadPoolExecutor() as executor:
        # log handler
        result_log = executor.submit(_log_)
        # printing for concurrency
        print(result_log.result())

    run.finish()
