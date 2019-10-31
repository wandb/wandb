#!/usr/bin/env python
"""An internal CLI used by the agent and for "headless" mode.
"""

import json
import logging
import os
import socket
import sys
import time
import traceback
import platform

import six
import wandb
from wandb import env
import wandb.io_wrap
import wandb.run_manager
import wandb.wandb_run
from wandb import util
from wandb.compat import windows


def headless(args):
    """Headless mode is where we start a monitoring / syncing
    process to watch an already-running user process. It's like
    `wandb run` for a user process that has already started.

    The user process that calls this waits for a signal that
    everything is ready, which is sent at the end of rm.wrap_existing_process
    """
    user_process_pid = args['pid']
    stdout_master_fd = args['stdout_master_fd']
    stderr_master_fd = args['stderr_master_fd']
    try:
        run = wandb.wandb_run.Run.from_environment_or_defaults()
        run.enable_logging()
        # Clear inited for the wandb process
        del os.environ[env.INITED]
        # Set global run so save can work
        wandb.run = run
        # Access history to avoid sync issues
        run.history

        rm = wandb.run_manager.RunManager(
            run, cloud=args['cloud'],
            port=args['port'])
        # We add a reference to _run_manager to enable wandb.save to work for tfevents files
        # TODO: REFACTOR
        run._run_manager = rm
        rm.wrap_existing_process(
            user_process_pid, stdout_master_fd, stderr_master_fd)
    except Exception as e:
        util.sentry_reraise(e)


def agent_run(args):
    """A version of `wandb run` that the agent uses to run things.
    """
    run = wandb.wandb_run.Run.from_environment_or_defaults()
    run.enable_logging()

    # TODO: better failure handling
    root = run.api.git.root
    # handle non-git directories
    if not root:
        root = os.path.abspath(os.getcwd())
        host = socket.gethostname()
        remote_url = 'file://{}{}'.format(host, root)

    run.save(program=args['program'])
    env = dict(os.environ)
    run.set_environment(env)

    try:
        rm = wandb.run_manager.RunManager(run, agent_run=True)
    except wandb.run_manager.Error:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        wandb.termerror('An Exception was raised during setup, see %s for full traceback.' %
                        util.get_log_file_path())
        wandb.termerror(exc_value)
        if 'permission' in str(exc_value):
            wandb.termerror(
                'Are you sure you provided the correct API key to "wandb login"?')
        lines = traceback.format_exception(
            exc_type, exc_value, exc_traceback)
        logging.error('\n'.join(lines))
    else:
        rm.run_user_process(args['program'], args['args'], env)


def main():
    wandb.try_to_set_up_global_logging()

    args = json.loads(sys.argv[1])
    command = args['command']
    if command == 'headless':
        headless(args)
    elif command == 'agent-run':
        agent_run(args)
    else:
        assert False


if __name__ == '__main__':
    main()
