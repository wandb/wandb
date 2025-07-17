import urllib.parse
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Union

import wandb
from wandb import env
from wandb.apis import InternalApi
from wandb.sdk.launch.sweeps.utils import handle_sweep_config_violations

from . import wandb_login

if TYPE_CHECKING:
    from wandb.wandb_controller import _WandbController


def _get_sweep_url(api, sweep_id):
    """Return sweep url if we can figure it out."""
    if api.api_key:
        if api.settings("entity") is None:
            viewer = api.viewer()
            if viewer.get("entity"):
                api.set_setting("entity", viewer["entity"])
        project = api.settings("project")
        if not project:
            return
        if api.settings("entity"):
            return "{base}/{entity}/{project}/sweeps/{sweepid}".format(
                base=api.app_url,
                entity=urllib.parse.quote(api.settings("entity")),
                project=urllib.parse.quote(project),
                sweepid=urllib.parse.quote(sweep_id),
            )


def sweep(
    sweep: Union[dict, Callable],
    entity: Optional[str] = None,
    project: Optional[str] = None,
    prior_runs: Optional[List[str]] = None,
) -> str:
    """Initialize a hyperparameter sweep.

    Search for hyperparameters that optimizes a cost function
    of a machine learning model by testing various combinations.

    Make note the unique identifier, `sweep_id`, that is returned.
    At a later step provide the `sweep_id` to a sweep agent.

    See [Sweep configuration structure](https://docs.wandb.ai/guides/sweeps/define-sweep-configuration)
    for information on how to define your sweep.

    Args:
      sweep: The configuration of a hyperparameter search.
        (or configuration generator).
        If you provide a callable, ensure that the callable does
        not take arguments and that it returns a dictionary that
        conforms to the W&B sweep config spec.
      entity: The username or team name where you want to send W&B
        runs created by the sweep to. Ensure that the entity you
        specify already exists. If you don't specify an entity,
        the run will be sent to your default entity,
        which is usually your username.
      project: The name of the project where W&B runs created from
        the sweep are sent to. If the project is not specified, the
        run is sent to a project labeled 'Uncategorized'.
      prior_runs: The run IDs of existing runs to add to this sweep.

    Returns:
      str: A unique identifier for the sweep.
    """
    if callable(sweep):
        sweep = sweep()
    """Sweep create for controller api and jupyter (eventually for cli)."""

    # Project may be only found in the sweep config.
    if project is None and isinstance(sweep, dict):
        project = sweep.get("project", None)

    if entity:
        env.set_entity(entity)
    if project:
        env.set_project(project)

    # Make sure we are logged in
    if wandb.run is None:
        wandb_login._login(_silent=True)
    api = InternalApi()
    sweep_id, warnings = api.upsert_sweep(sweep, prior_runs=prior_runs)
    handle_sweep_config_violations(warnings)
    print("Create sweep with ID:", sweep_id)  # noqa: T201
    sweep_url = _get_sweep_url(api, sweep_id)
    if sweep_url:
        print("Sweep URL:", sweep_url)  # noqa: T201
    return sweep_id


def controller(
    sweep_id_or_config: Optional[Union[str, Dict]] = None,
    entity: Optional[str] = None,
    project: Optional[str] = None,
) -> "_WandbController":
    """Public sweep controller constructor.

    Examples:
    ```python
    import wandb

    tuner = wandb.controller(...)
    print(tuner.sweep_config)
    print(tuner.sweep_id)
    tuner.configure_search(...)
    tuner.configure_stopping(...)
    ```

    """
    from ..wandb_controller import _WandbController

    c = _WandbController(
        sweep_id_or_config=sweep_id_or_config, entity=entity, project=project
    )
    return c
