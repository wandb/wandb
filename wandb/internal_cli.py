#!/usr/bin/env python
"""An internal CLI used by the agent and for "headless" mode.
"""

import json
import os
import socket
import sys
import time

import wandb.api
import wandb.run_manager
import wandb.wandb_run


def headless(args):
    """Headless mode is where we start a monitoring / syncing
    process to watch an already-running user process. It's like
    `wandb run` for a user process that has already started.

    In this situation the GQL Run has already been created in
    `wandb.init()`.
    """
    user_process_pid = args['pid']
    stdout_master_fd = args['stdout_master_fd']
    stderr_master_fd = args['stderr_master_fd']

    run = wandb.wandb_run.Run.from_environment_or_defaults()

    api = wandb.api.Api()
    api.set_current_run_id(run.id)

    rm = wandb.run_manager.RunManager(
        api, run, cloud=args['cloud'], job_type=args['job_type'],
        port=args['port'], program=args['program'])
    rm.wrap_existing_process(
        user_process_pid, stdout_master_fd, stderr_master_fd)


def agent_run(args):
    """A version of `wandb run` that the agent uses to run things.
    """
    run = wandb.wandb_run.Run.from_environment_or_defaults()

    api = wandb.api.Api()
    api.set_current_run_id(run.id)

    # TODO: better failure handling
    root = api.git.root
    remote_url = api.git.remote_url
    host = socket.gethostname()
    # handle non-git directories
    if not root:
        root = os.path.abspath(os.getcwd())
        remote_url = 'file://%s%s' % (host, root)

    upsert_result = api.upsert_run(id=run.storage_id,
                                   name=run.id,
                                   project=api.settings("project"),
                                   entity=api.settings("entity"),
                                   config=run.config.as_dict(), description=run.description, host=host,
                                   program_path=args['program'], repo=remote_url, sweep_name=run.sweep_id)
    run.storage_id = upsert_result['id']
    env = dict(os.environ)
    run.set_environment(env)

    try:
        rm = wandb.run_manager.RunManager(api, run)
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
        logger.error('\n'.join(lines))
    else:
        rm.run_user_process(args['program'], args['args'], env)


def main():
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
