from typing import Callable, Dict, Optional, Union
import urllib.parse

import wandb
from wandb import env
from wandb.apis import InternalApi
from wandb.util import handle_sweep_config_violations

from . import wandb_login


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
    entity: str = None,
    project: str = None,
) -> str:
    """Initialize a hyperparameter sweep.

    To generate hyperparameter suggestions from the sweep and use them
    to train a model, call `wandb.agent` with the sweep_id returned by
    this command. For command line functionality, see the command line
    tool `wandb sweep` (https://docs.wandb.ai/ref/cli/wandb-sweep).

    Args:
      sweep: dict, SweepConfig, or callable. The sweep configuration
        (or configuration generator). If a dict or SweepConfig,
        should conform to the W&B sweep config specification
        (https://docs.wandb.ai/guides/sweeps/configuration). If a
        callable, should take no arguments and return a dict that
        conforms to the W&B sweep config spec.
      entity: str (optional). An entity is a username or team name
        where you're sending runs. This entity must exist before you
        can send runs there, so make sure to create your account or
        team in the UI before starting to log runs.  If you don't
        specify an entity, the run will be sent to your default
        entity, which is usually your username. Change your default
        entity in [Settings](wandb.ai/settings) under "default
        location to create new projects".
      project: str (optional). The name of the project where you're
        sending the new run. If the project is not specified, the
        run is put in an "Uncategorized" project.

    Returns:
      sweep_id: str. A unique identifier for the sweep.

    Examples:
        Basic usage
        <!--yeadoc-test:one-parameter-sweep-->
        ```python
        import wandb
        sweep_configuration = {
            "name": "my-awesome-sweep",
            "metric": {"name": "accuracy", "goal": "maximize"},
            "method": "grid",
            "parameters": {
                "a": {
                    "values": [1, 2, 3, 4]
                }
            }
        }

        def my_train_func():
            # read the current value of parameter "a" from wandb.config
            wandb.init()
            a = wandb.config.a

            wandb.log({"a": a, "accuracy": a + 1})

        sweep_id = wandb.sweep(sweep_configuration)

        # run the sweep
        wandb.agent(sweep_id, function=my_train_func)
        ```
    """

    if callable(sweep):
        sweep = sweep()
    """Sweep create for controller api and jupyter (eventually for cli)."""
    if entity:
        env.set_entity(entity)
    if project:
        env.set_project(project)

    # Make sure we are logged in
    if wandb.run is None:
        wandb_login._login(_silent=True)
    api = InternalApi()
    sweep_id, warnings = api.upsert_sweep(sweep)
    handle_sweep_config_violations(warnings)
    print("Create sweep with ID:", sweep_id)
    sweep_url = _get_sweep_url(api, sweep_id)
    if sweep_url:
        print("Sweep URL:", sweep_url)
    return sweep_id


def controller(
    sweep_id_or_config: Optional[Union[str, Dict]] = None,
    entity: Optional[str] = None,
    project: Optional[str] = None,
):
    """Public sweep controller constructor.

    Usage:
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
