from .wandb_trial import run
from .wandb_trial import set_controller
from .wandb_trial import wandb_schedule

import sys
import wandb


def reporter(**args):
    #print("Report:", args)
    wandb.log(args)
    pass

def _call_run(func):
    run = wandb.init()
    # force a config update
    run.config.update({})
    # prefer using wandb.config over command line since types will be preserved
    config = dict(run.config)
    config.pop('_wandb_tune_run')
    #print("CONFIG", config)
    func(config, reporter)


def init_run(func=None):
    #print("INIT", sys.argv)
    for arg in sys.argv[1:]:
        if arg.startswith('--_wandb_tune_run='):
            # call func
            _call_run(func)
            sys.exit(0)





#__all__ = ['init', 'run']
