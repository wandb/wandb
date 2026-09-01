"""Runs a sweep scheduler: wandb-core drives, this process optimizes.

The client initializes a scheduler session in wandb-core, builds the
optimizer from the sweep facts core returns, and exchanges tasks until the
scheduler is done. Signals are handled here: only this process receives
ctrl-c (wandb-core runs in its own session), so the first one is
translated into a graceful stop request and the second one force-quits.
"""

from __future__ import annotations

import signal
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import yaml

import wandb
from wandb.errors import term
from wandb.proto import wandb_sweep_scheduler_pb2 as sspb
from wandb.sdk import wandb_setup
from wandb.sdk.lib import wbauth
from wandb.sdk.sweeps.scheduler.optimizer import Optimizer
from wandb.sdk.sweeps.scheduler.ipc import (
    SchedulerTaskExchange,
    describe_done,
    forget_discards,
)
from wandb.sdk.sweeps.sweep_info import SweepInfo

# Init is one wandb-core round trip to the W&B backend, registering the
# scheduler and fetching the sweep's config, so allow for a slow network.
_INIT_TIMEOUT_SECONDS = 30

OptimizerFactory = Callable[[SweepInfo], Optimizer]
"""Builds the optimizer once the sweep's config is known."""


@dataclass
class SchedulerOptions:
    """How the scheduler drives a sweep, independent of the search strategy.

    `poll_interval_s` is how long wandb-core waits between polls of the
    sweep's runs, and `batch_size` is how many runs to keep in flight.
    """

    poll_interval_s: float = 5.0
    batch_size: int = 1


def run_scheduler(
    *,
    entity: str,
    project: str,
    sweep_id: str,
    make_optimizer: OptimizerFactory,
    batch_size: int,
    poll_interval: float,
) -> sspb.SweepSchedulerServerDoneTask:
    """Drive a sweep until its scheduler stops.

    Args:
        entity: The entity that owns the sweep.
        project: The project the sweep belongs to.
        sweep_id: The sweep's short id.
        make_optimizer: Builds the optimizer from the sweep's facts.
        batch_size: Number of runs to keep in flight at once.
        poll_interval: Seconds between polls of the sweep's runs.

    Returns:
        The scheduler's Done task, describing why it stopped.

    Raises:
        wandb.Error: If the scheduler stopped because of a failure.

    Raises:
        ValueError: If entity, project or sweep_id is empty.
    """
    if not entity or not project or not sweep_id:
        raise ValueError("entity, project and sweep_id must be non-empty")

    singleton = wandb_setup.singleton()

    # wandb-core makes every backend call for the scheduler, so the
    # session's credentials must be resolved before it starts: without
    # them the sweep simply looks missing.
    if not wbauth.authenticate_session(
        host=singleton.settings.base_url,
        source="wandb sweep-scheduler",
        no_offline=True,
    ):
        raise wandb.Error(
            "Not authenticated. Run `wandb login` to run a sweep scheduler."
        )

    service = singleton.ensure_service()

    async def init() -> sspb.SweepSchedulerServerInitResponse:
        handle = await service.init_sweep_scheduler(
            singleton.settings,
            entity=entity,
            project=project,
            sweep_id=sweep_id,
            batch_size=batch_size,
            poll_interval_seconds=poll_interval,
        )
        return await handle.wait_async(timeout=_INIT_TIMEOUT_SECONDS)

    init_response = singleton.asyncer.run(init)

    sweep = SweepInfo(
        id=sweep_id,
        name=init_response.display_name or sweep_id,
        entity=entity,
        project=project,
        config=yaml.safe_load(init_response.sweep_config) or {},
    )
    optimizer = make_optimizer(sweep)
    exchange = SchedulerTaskExchange(service, init_response.session_id, optimizer)

    previous_handler = _install_sigint_handler(
        singleton.asyncer, service, init_response.session_id
    )
    try:
        done = singleton.asyncer.run(exchange.run)
    finally:
        if previous_handler is not None:
            signal.signal(signal.SIGINT, previous_handler)

    forget_discards(optimizer, done)
    message, is_error = describe_done(done)
    if is_error:
        term.termerror(f"Sweep scheduler for {sweep.name} exited: {message}.")
        raise wandb.Error(f"The sweep scheduler failed: {message}.")

    term.termlog(f"Sweep scheduler for {sweep.name} exited: {message}.")
    return done


def _install_sigint_handler(
    asyncer: Any,
    service: Any,
    scheduler_id: str,
) -> Any:
    """Translate the first ctrl-c into a graceful stop.

    The scheduler finishes its current step and answers the outstanding
    poll with a Done task, so the task exchange exits cleanly and the
    sweep stays resumable. A second ctrl-c raises KeyboardInterrupt as
    usual, which cancels the exchange.

    Only the main thread may install a handler, so off it the scheduler
    runs without this translation.

    Returns:
        The previous SIGINT handler to restore, or None if none was
        installed.
    """
    state = {"interrupted": False}

    def on_sigint(signum: int, frame: Any) -> None:
        if state["interrupted"]:
            raise KeyboardInterrupt
        state["interrupted"] = True

        term.termlog(
            "Interrupted. Finishing the current scheduler step; "
            "press ctrl-c again to force quit."
        )
        asyncer.run_soon(
            lambda: service.stop_sweep_scheduler(scheduler_id),
            daemon=True,
        )

    try:
        return signal.signal(signal.SIGINT, on_sigint)
    except ValueError:
        # Not the main thread, where alone a handler may be installed. The
        # scheduler still stops when its client exits, just without the
        # finish-this-step handshake.
        return None
