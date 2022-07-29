#!/usr/bin/env python
import argparse
from typing import Optional

import wandb


def run_first() -> str:
    with wandb.init() as run:
        assert not run.resumed
        wandb.log(dict(m1=1))
        wandb.log(dict(m2=2))
        wandb.log(dict(m3=3))
        run_id = run.id
    return run_id


def run_again(run_id: str, resume: Optional[str]) -> None:
    kwargs = dict(id=run_id)
    if resume:
        kwargs["resume"] = resume
    with wandb.init(**kwargs) as run:
        if run.resumed:
            print("RUN_STATE: run resumed")
        else:
            print("RUN_STATE: run not resumed")
        wandb.log(dict(m1=11))
        wandb.log(dict(m2=22))
        wandb.log(dict(m4=44))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", type=str)
    args = parser.parse_args()

    run_id = run_first()
    run_again(run_id=run_id, resume=args.resume)


if __name__ == "__main__":
    main()
