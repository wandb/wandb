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
if os.path.exists(os.path.join(env.get_dir(os.getcwd()), '.wandb')):
    __stage_dir__ = '.wandb' + os.sep
elif os.path.exists(os.path.join(env.get_dir(os.getcwd()), 'wandb')):
    __stage_dir__ = "wandb" + os.sep
else:
    __stage_dir__ = None

SCRIPT_PATH = os.path.abspath(sys.argv[0])
START_TIME = time.time()
LIB_ROOT = os.path.join(os.path.dirname(__file__), '..')
IS_GIT = os.path.exists(os.path.join(LIB_ROOT, '.git'))


def wandb_dir():
    return os.path.join(env.get_dir(os.getcwd()), __stage_dir__ or ("wandb" + os.sep))


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
WARN_STRING = click.style('WARNING', fg='yellow')
PRINTED_MESSAGES = set()


# TODO(adrian): if output has been redirected, make this write to the original STDERR
# so it doesn't get logged to the backend
def termlog(string='', newline=True, repeat=True):
    """Log to standard error with formatting.

    Args:
            string (str, optional): The string to print
            newline (bool, optional): Print a newline at the end of the string
            repeat (bool, optional): If set to False only prints the string once per process
    """
    if string:
        line = '\n'.join(['{}: {}'.format(LOG_STRING, s)
                          for s in string.split('\n')])
    else:
        line = ''
    if not repeat and line in PRINTED_MESSAGES:
        return
    PRINTED_MESSAGES.add(line)
    click.echo(line, file=sys.stderr, nl=newline)


def termwarn(string, **kwargs):
    string = '\n'.join(['{} {}'.format(WARN_STRING, s)
                        for s in string.split('\n')])
    termlog(string=string, newline=True, **kwargs)


def termerror(string, **kwargs):
    string = '\n'.join(['{} {}'.format(ERROR_STRING, s)
                        for s in string.split('\n')])
    termlog(string=string, newline=True, **kwargs)


__all__ = [
    '__stage_dir__', 'SCRIPT_PATH', 'START_TIME', 'wandb_dir',
    '_set_stage_dir', 'Error', 'WandbWarning', 'LOG_STRING', 'ERROR_STRING', 'termlog', 'termwarn', 'termerror'
]
