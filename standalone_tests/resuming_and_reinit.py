import sys
import time

import wandb


def main(args):
    run_id = wandb.util.generate_id()
    try:
        wandb.init(project="resuming", resume="must", id=run_id)
    except wandb.Error:
        print("Confirmed we can't resume a non-existent run with must")

    wandb.init(project="resuming", resume="allow", id=run_id)
    print("Run start time: ", wandb.run.start_time)
    for i in range(10):
        print(f"Logging step {i}")
        wandb.log({"metric": i})
        time.sleep(1)
    wandb.join()
    print("Run finished at: ", int(time.time()))

    print("Sleeping 5 seconds...")
    time.sleep(5)

    wandb.init(project="resuming", resume="allow", id=run_id, reinit=True)
    print("Run starting step: ", wandb.run.history._step)
    print("Run start time: ", int(wandb.run.start_time))
    print("Time travel: ", int(time.time() - wandb.run.start_time))
    for i in range(10):
        print("Resumed logging step %i" % i)
        wandb.log({"metric": i})
        time.sleep(1)
    wandb.join()

    try:
        wandb.init(project="resuming", resume="never", id=run_id, reinit=True)
        raise ValueError("I was allowed to resume!")
    except wandb.Error:
        print("Confirmed we can't resume run when never")

    api = wandb.Api()
    run = api.run(f"resuming/{run_id}")

    # TODO: This is showing a beast bug, we're not syncing the last history row
    print("History")
    print(run.history())

    print("System Metrics")
    print(run.history(stream="system"))


if __name__ == "__main__":
    main(sys.argv)
