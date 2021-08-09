#!/usr/bin/env python
"""checkpoint basic.

---
id: 99.0.1
check-ext-wandb: {}
assert:
  - :wandb:runs_len: 4
  - :wandb:runs[0][exitcode]: 0
  - :wandb:runs[1][exitcode]: 0
  - :wandb:runs[2][exitcode]: 0
  - :wandb:runs[3][exitcode]: 0
"""

import wandb


def do_stuff(run, log_checkpoint: bool = False):
    chkpnt = 0
    h1 = dict(run.summary).get("h1", 1.0)
    for i in range(20):
        run.log(dict(h1=h1))
        h1 = h1 * (1 + run.config.c1)
        if not log_checkpoint:
            continue
        if i % 4 == 0:
            run.log_checkpoint()
            chkpnt += 1


def run_base() -> str:
    run_id = None
    cfg = dict(c1=0.05)
    with wandb.init(config=cfg) as run:
        do_stuff(run, log_checkpoint=True)
        run_id = run.id
    assert run_id
    return run_id


def run_branch(ckpt: str, mult):
    with wandb.init(from_checkpoint=ckpt) as run:
        cfg = dict(c1=run.config.c1 * mult)
        run.config.update(cfg, allow_val_change=True)
        do_stuff(run)


def main():
    run_id = run_base()
    run_branch(f"{run_id}:v3", 2)
    run_branch(f"{run_id}:v1", 3)
    run_branch(f"{run_id}:latest", 4)


if __name__ == "__main__":
    main()
