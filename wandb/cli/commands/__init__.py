from wandb.cli.commands.artifact import artifact
from wandb.cli.commands.beta import beta
from wandb.cli.commands.docker import docker, docker_run
from wandb.cli.commands.importer import importer
from wandb.cli.commands.init import init, projects
from wandb.cli.commands.launch import job, launch, launch_agent, launch_sweep, scheduler
from wandb.cli.commands.login import login
from wandb.cli.commands.magic import magic
from wandb.cli.commands.offline import disabled, off, offline
from wandb.cli.commands.online import enabled, on, online
from wandb.cli.commands.pull import pull
from wandb.cli.commands.restore import restore
from wandb.cli.commands.server import local, server
from wandb.cli.commands.service import service
from wandb.cli.commands.status import status
from wandb.cli.commands.sweep import agent, controller, sweep
from wandb.cli.commands.sync import gc, sync
from wandb.cli.commands.verify import verify

__all__ = (
    "agent",
    "artifact",
    "beta",
    "controller",
    "disabled",
    "docker",
    "docker_run",
    "enabled",
    "gc",
    "importer",
    "init",
    "job",
    "launch",
    "launch_agent",
    "launch_sweep",
    "login",
    "local",
    "magic",
    "off",
    "offline",
    "on",
    "online",
    "projects",
    "pull",
    "restore",
    "scheduler",
    "server",
    "service",
    "status",
    "sweep",
    "sync",
    "verify",
)
