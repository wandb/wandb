"""
config tests.
"""

import os
import sys
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


def test_run_pub_config(fake_run, record_q, records_util):
    run = fake_run()
    run.config.t = 1
    run.config.t2 = 2

    r = records_util(record_q)
    assert len(r.records) == 2
    assert len(r.summary) == 0
    configs = r.configs
    assert len(configs) == 2
    # TODO(jhr): check config vals


def test_run_pub_history(fake_run, record_q, records_util):
    run = fake_run()
    run.log(dict(this=1))
    run.log(dict(that=2))

    r = records_util(record_q)
    assert len(r.records) == 2
    assert len(r.summary) == 0
    history = r.history
    assert len(history) == 2
    # TODO(jhr): check history vals


def test_save_symlink(wandb_init_run):
    f1 = os.path.join(wandb_init_run.dir, "test_file.txt")
    sf = os.path.join(wandb_init_run.dir, "symlink_file")
    with open(f1, "w") as f:
        f.write("test string")
        f.close()

    os.symlink(f1, sf)
    wandb_init_run.save(sf)
    assert os.path.islink(sf)


# def test_sarve_symlink2(live_mock_server, test_settings):
#     test_settings.update({"symlink": False})
#     run = wandb.init(settings=test_settings)
#     f1 = os.path.join(run.dir, "test_file.txt")
#     sf = os.path.join(run.dir, "symlink_file")
#     with open(f1, 'w') as f:
#         f.write("test string")
#         f.close()

#     os.symlink(f1, sf)
#     run.save(sf)
#     assert os.path.islink(sf)
