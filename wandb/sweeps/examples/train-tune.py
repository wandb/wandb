#!/usr/bin/env python

import wandb
import argparse
import sys
from wandb.sweeps.config import tune
from wandb.sweeps.config.hyperopt import hp
from wandb.sweeps.config.tune.schedulers import AsyncHyperBandScheduler
from wandb.sweeps.config.tune.suggest.hyperopt import HyperOptSearch
from datetime import datetime

# define command line options
parser = argparse.ArgumentParser()
parser.add_argument("--sweep", type=str, help="create sweep")
parser.add_argument("--file", type=str, help="save sweep config")
parser.add_argument("--controller", action="store_true", help="run local controller")
parser.add_argument("--create", action="store_true", default=True, help="create sweep")
parser.add_argument("--nocreate", action="store_false", dest="create", default=True, help="do not create sweep")
args, more_args = parser.parse_known_args()
if more_args:
    print("[WARNING] ignored extra arguments: {}".format(', '.join(more_args)))

# define param defaults
config_defaults = dict(
    epochs=12,
    learning_rate=12,
    width=1.2,
    height=3.4,
    activation="relu",
    )

# define sweeps
sweep_registry = dict(
    hyperopt=lambda:
        tune.run(
            parser.prog,
            search_alg=HyperOptSearch(
                dict(
                    width=hp.uniform("width", 0, 20),
                    height=hp.uniform("height", -100, 100),
                    activation=hp.choice("activation", ["relu", "tanh"])),
                metric="mean_loss",
                mode="min"),
            scheduler=AsyncHyperBandScheduler(
                metric="mean_loss",
                mode="min"),
            num_samples=10,
            ).set(
                name=datetime.now().strftime("hyperopt_%y%m%d%H%M"),
                settings=dict(
                    agent_command_config_args=False,
                    agent_report_interval=0,
                    ),
                )
    )


def train():
    run = wandb.init(config=config_defaults)
    shorten = dict(width="w", height="h", activation="a")
    clean = lambda x: '{:0.1f}'.format(x) if isinstance(x, float) else x
    run.name = "run:" + ','.join([
        '{}={}'.format(shorten.get(k), clean(v)) for k, v in dict(run.config).items() if k in shorten])
    run.save()
    conf = dict(wandb.config)
    value = conf.get("width") + conf.get("height")
    wandb.log(dict(mean_loss=value))


def main():
    if args.sweep:
        sweep_config = sweep_registry.get(args.sweep)
        if not sweep_config:
            print("[ERROR] can not find sweep: {}".format(args.sweep))
            sys.exit(1)
        if args.file:
            # construct config
            sweep_config = sweep_config()
            sweep_config.save(args.file)
        if args.create:
            sweep_id = wandb.sweep(sweep_config)
            if args.controller:
                sweep = wandb.controller(sweep_id)
                sweep.run()
        return
    train()


if __name__ == "__main__":
    main()
