"""Core variables, functions, and classes that we want in the wandb
module but are also used in modules that import the wandb module.

The purpose of this module is to break circular imports.
"""

import os
import string
import sys
import time

import click

from . import env
from . import io_wrap


# We use the hidden version if it already exists, otherwise non-hidden.
if os.path.exists(os.path.join(env.get_dir('./'), '.wandb')):
    __stage_dir__ = '.wandb/'
elif os.path.exists(os.path.join(env.get_dir('./'), 'wandb')):
    __stage_dir__ = "wandb/"
else:
    __stage_dir__ = None

SCRIPT_PATH = os.path.abspath(sys.argv[0])
START_TIME = time.time()


def wandb_dir():
    return os.path.join(env.get_dir('./'), __stage_dir__ or "wandb/")


def _set_stage_dir(stage_dir):
    # Used when initing a new project with "wandb init"
    global __stage_dir__
    __stage_dir__ = stage_dir


class Error(Exception):
    """Base W&B Error"""
    # For python 2 support

    def encode(self, encoding):
        return self.message


class WandbWarning(Warning):
    """Base W&B Warning"""
    pass


LOG_STRING = click.style('wandb', fg='blue', bold=True)
ERROR_STRING = click.style('ERROR', bg='red', fg='green')


# TODO(adrian): if output has been redirected, make this write to the original STDERR
# so it doesn't get logged to the backend
def termlog(string='', newline=True):
    if string:
        line = '\n'.join(['%s: %s' % (LOG_STRING, s)
                          for s in string.split('\n')])
    else:
        line = ''
    click.echo(line, file=sys.stderr, nl=newline)


def termerror(string):
    string = '\n'.join(['%s: %s' % (ERROR_STRING, s)
                        for s in string.split('\n')])
    termlog(string=string, newline=True)


__all__ = [
    '__stage_dir__', 'SCRIPT_PATH', 'START_TIME', 'wandb_dir',
    '_set_stage_dir', 'Error', 'WandbWarning', 'LOG_STRING', 'ERROR_STRING', 'termlog', 'termerror'
]
