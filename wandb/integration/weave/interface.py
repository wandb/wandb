"""Internal APIs for integrating with weave.

The public functions here are intended to be called by weave and care should
be taken to maintain backward compatibility.
"""

from __future__ import annotations

import dataclasses

from wandb.sdk import wandb_setup


@dataclasses.dataclass(frozen=True)
class RunPath:
    entity: str
    project: str
    run_id: str


def active_run_path() -> RunPath | None:
    """Returns the path of an initialized, unfinished run.

    Returns None if all initialized runs are finished. If there is
    more than one active run, an arbitrary path is returned.
    The run may be finished by the time its path is returned.

    Thread-safe.
    """
    singleton = wandb_setup.singleton()

    if run := singleton.most_recent_active_run:
        return RunPath(
            entity=run.entity,
            project=run.project,
            run_id=run.id,
        )

    return None
