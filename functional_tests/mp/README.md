

# Test cases

Test | Description
---  | ---
[0.mp.01-simple-nofinish](01-simple-nofinish.py) | no finish on run, manager does finish
[0.mp.02-sequential.py](02-sequential.py) | sequential runs
[0.mp.03-parent-child.py](03-parent-child.py) | run in parent and child process
[0.mp.04-pool.py](04-pool.py) | spawn multiple processes with runs
[0.mp.05-pool-nofinish.py](05-pool-nofinish.py) | spawn multiple processes with runs (no finish)
[0.mp.06-share-child.py](06-share-child.py) | pass a run to a child process *NOT SUPPORTED YET*
[0.mp.07-attach.py](07-attach.py) | use wandb attach in a spawned run *NOT SUPPORTED YET*
[0.mp.08-multiple.py](08-multiple.py) | multiple runs in same process *NOT SUPPORTED YET*
