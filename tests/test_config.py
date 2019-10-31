import pytest
import os
from click.testing import CliRunner

from wandb import wandb_config as config
from wandb import env
import yaml
import sys
import six
import os
import argparse
import textwrap


def test_config_empty_by_default():
    with CliRunner().isolated_filesystem():
        conf = config.Config()
        assert list(conf.keys()) == []


def test_config_docker_env():
    try:
        os.environ[env.DOCKER] = "ubuntu"
        with CliRunner().isolated_filesystem():
            conf = config.Config()
            assert conf["_wandb"]["docker_image"] == "ubuntu"
    finally:
        del os.environ[env.DOCKER]


def test_config_docker_env_digest():
    try:
        os.environ[env.DOCKER] = "ubuntu@sha25612345678901234567890"
        with CliRunner().isolated_filesystem():
            conf = config.Config()
            assert conf["_wandb"]["docker_image"] == "ubuntu"
            assert conf["_wandb"]["docker_digest"] == "sha25612345678901234567890"
    finally:
        del os.environ[env.DOCKER]


def test_config_set_items():
    with CliRunner().isolated_filesystem():
        conf = config.Config()
        conf['a'] = 15
        conf.b = 16
        assert list(conf.keys()) == ['a', 'b']
        assert conf.a == 15
        assert conf['b'] == 16


def test_config_accepts_dict_vals():
    with CliRunner().isolated_filesystem():
        conf = config.Config()
        conf['a'] = {'b': 14, 'c': 15}
        assert conf.a == {'b': 14, 'c': 15}


def test_config_update_accepts_dict_vals():
    with CliRunner().isolated_filesystem():
        conf = config.Config()
        conf.update({'b': 14, 'c': 15})
        assert conf.b == 14
        assert conf.c == 15

@pytest.mark.skipif(os.getenv("NO_ML") == "true", reason="No numpy in NO_ML")
def test_config_wild_values():
    import numpy as np
    with CliRunner().isolated_filesystem():
        conf = config.Config(run_dir=".")
        conf['numpy'] = np.random.normal(size=(10,))
        conf['class'] = CliRunner()
        conf['list'] = [np.random.normal(1), 32.5]
        conf['dir'] = {"numpy": np.random.normal(size=(10,))}

        conf2 = config.Config(config_paths=['config.yaml'])
        assert len(conf2['numpy']) == 10
        assert len(conf2['dir']['numpy']) == 10
        assert "CliRunner" in conf2['class']
        assert conf2['list'][-1] == 32.5

def test_config_persists():
    with CliRunner().isolated_filesystem():
        conf = config.Config(run_dir='.')
        conf['a'] = 5
        conf.b = 14.3

        conf2 = config.Config(config_paths=['config.yaml'])
        assert conf2['a'] == 5
        assert conf2.b == 14.3


def test_config_defaults():
    with CliRunner().isolated_filesystem():
        open('config-defaults.yaml', 'w').write(textwrap.dedent("""\
            wandb_version: 1

            a:
              desc: the number nineteen
              value: 19
            b:
              desc: null
              value: a_cow
            c: 141912
            """))
        conf = config.Config(wandb_dir='.')
        assert conf.a == 19
        assert conf.b == 'a_cow'
        assert conf.c == 141912


def test_config_file_overrides():
    with CliRunner().isolated_filesystem():
        open('config-defaults.yaml', 'w').write(textwrap.dedent("""\
            wandb_version: 1

            a:
              desc: the number nineteen
              value: 19
            b:
              desc: null
              value: a_cow
            """))
        open('config-special.yaml', 'w').write(textwrap.dedent("""\
            wandb_version: 1

            a:
              desc: the number nineteen
              value: 43
            """))
        conf = config.Config(wandb_dir='.', config_paths=[
                             'config-special.yaml'])
        assert conf.a == 43
        assert conf.b == 'a_cow'
