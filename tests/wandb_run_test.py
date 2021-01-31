"""
config tests.
"""

import pytest
import yaml
import wandb
from wandb import wandb_sdk


def test_run_basic():
    s = wandb.Settings()
    c = dict(param1=2, param2=4)
    run = wandb_sdk.wandb_run.Run(settings=s, config=c)
    assert dict(run.config) == dict(param1=2, param2=4)


def test_run_sweep():
    s = wandb.Settings()
    c = dict(param1=2, param2=4)
    sw = dict(param3=9)
    run = wandb_sdk.wandb_run.Run(settings=s, config=c, sweep_config=sw)
    assert dict(run.config) == dict(param1=2, param2=4, param3=9)


def test_run_sweep_overlap():
    s = wandb.Settings()
    c = dict(param1=2, param2=4)
    sw = dict(param2=8, param3=9)
    run = wandb_sdk.wandb_run.Run(settings=s, config=c, sweep_config=sw)
    assert dict(run.config) == dict(param1=2, param2=8, param3=9)
