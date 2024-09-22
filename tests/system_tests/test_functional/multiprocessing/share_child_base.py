"""Example of sharing a run object with a child process."""

import argparse
import multiprocessing as mp

import wandb


def process_child(run):
    """Log to the shared run object."""
    run.config.c2 = 22
    run.log({"s1": 21})


def main():
    with wandb.init() as run:
        assert run == wandb.run

        run.config.c1 = 11
        run.log({"s1": 11})

        p = mp.Process(
            target=process_child,
            kwargs=dict(run=run),
        )
        p.start()
        p.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="A simple example of sharing a run object with a child process."
    )
    parser.add_argument(
        "--start-method",
        type=str,
        choices=["spawn", "forkserver", "fork"],
        default="spawn",
        help="Method to start the process (default is spawn)",
    )
    args = parser.parse_args()
    mp.set_start_method(args.start_method, force=True)
    main()
