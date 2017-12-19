import pytest
import os
from click.testing import CliRunner

from wandb import config
import yaml
import sys
import os
import argparse
import textwrap


def test_config_empty_by_default():
    with CliRunner().isolated_filesystem():
        conf = config.Config()
        assert list(conf.keys()) == []


def test_config_empty_by_default():
    with CliRunner().isolated_filesystem():
        conf = config.Config()
        conf['a'] = 15
        conf.b = 16
        assert list(conf.keys()) == ['a', 'b']
        assert conf.a == 15
        assert conf['b'] == 16


@pytest.mark.skip(reason='Very TDD')
def test_config_accepts_dict_vals():
    with CliRunner().isolated_filesystem():
        conf = config.Config()
        conf['a'] = {'b': 14, 'c': 15}


def test_config_persists():
    with CliRunner().isolated_filesystem():
        conf = config.Config(run_dir='.')
        conf['a'] = 5
        conf.b = 14.3

        conf2 = config.Config(config_paths=['config.yaml'])
        assert conf2['a'] == 5
        assert conf2.b == 14.3


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
            """))
        conf = config.Config(wandb_dir='.')
        assert conf.a == 19
        assert conf.b == 'a_cow'


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
