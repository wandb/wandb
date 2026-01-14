"""Core variables, functions, and classes that we want in the wandb
module but are also used in modules that import the wandb module.

The purpose of this module is to break circular imports.
"""

import os
import tempfile
import time

import wandb
from wandb import env

# We use the hidden version if it already exists, otherwise non-hidden.
if os.path.exists(os.path.join(env.get_dir(os.getcwd()), ".wandb")):
    __stage_dir__ = ".wandb" + os.sep
elif os.path.exists(os.path.join(env.get_dir(os.getcwd()), "wandb")):
    __stage_dir__ = "wandb" + os.sep
else:
    __stage_dir__ = None

wandb.START_TIME = time.time()


def wandb_dir(root_dir=None):
    if root_dir is None or root_dir == "":
        try:
            cwd = os.getcwd()
        except OSError:
            wandb.termwarn("os.getcwd() no longer exists, using system temp directory")
            cwd = tempfile.gettempdir()
        root_dir = env.get_dir(cwd)
    path = os.path.join(root_dir, __stage_dir__ or ("wandb" + os.sep))
    if not os.access(root_dir, os.W_OK):
        wandb.termwarn(
            f"Path {path} wasn't writable, using system temp directory", repeat=False
        )
        path = os.path.join(tempfile.gettempdir(), __stage_dir__ or ("wandb" + os.sep))
    return path


def _set_stage_dir(stage_dir):
    # Used when initing a new project with "wandb init"
    global __stage_dir__
    __stage_dir__ = stage_dir


__all__ = [
    "__stage_dir__",
    "START_TIME",
    "wandb_dir",
    "_set_stage_dir",
]
