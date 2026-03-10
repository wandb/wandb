"""Aviato integration for W&B.

Provides ``SandboxSession``, a subclass of ``aviato.Session`` that
automatically injects W&B credentials, tags sandboxes with the run name,
and logs sandbox IDs to the active wandb run.

Usage::

    import wandb

    run = wandb.init(project="my-project")
    with run.SandboxSession() as session:
        sb = session.sandbox(container_image="python:3.11")
        # sb has WANDB_API_KEY, WANDB_ENTITY, WANDB_PROJECT
        # sb is tagged with the wandb run name
        # sb's sandbox_id is logged to wandb on start
"""

from wandb.integration.aviato.session import SandboxSession

__all__ = ["SandboxSession"]
