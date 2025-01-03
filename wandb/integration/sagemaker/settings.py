from __future__ import annotations

import wandb

from . import resources


def update_run_settings(settings: wandb.Settings) -> None:
    """Update a run's settings when using SageMaker.

    This may set the run's ID and group and change arbitrary
    other settings based on the SageMaker secrets file.
    """
    if run := resources.run_id_and_group():
        settings.run_id, settings.run_group = run

    if env := resources.parse_sm_secrets():
        settings.update_from_env_vars(env)
