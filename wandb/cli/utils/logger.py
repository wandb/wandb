import os

import wandb


# Send cli logs to wandb/debug-cli.<username>.log by default and fallback to a temp dir.
def get_wandb_dir():
    import tempfile

    path = wandb.old.core.wandb_dir(wandb.env.get_dir())
    if not os.path.exists(path):
        path = tempfile.gettempdir()
    return path


def get_username():
    import getpass

    try:
        return getpass.getuser()
    except KeyError:
        # getuser() could raise KeyError in restricted environments like
        # chroot jails or docker containers. Return user id in these cases.
        return str(os.getuid())


def get_wandb_cli_log_path():
    return os.path.join(get_wandb_dir(), f"debug-cli.{get_username()}.log")
