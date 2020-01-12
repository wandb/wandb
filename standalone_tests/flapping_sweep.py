"""Create a sweep with `python flapping_sweep.py create`"""
import wandb
import sys

if len(sys.argv) > 1 and sys.argv[1] == "create":
    sweep_id = wandb.sweep(dict(method='random', program="flapping_sweep.py", parameters=dict(lr=dict(min=0.01, max=0.10))))
    print("Run `wandb agent %s`" % sweep_id)
else:
    raise ValueError("I'm a bad sweep")
