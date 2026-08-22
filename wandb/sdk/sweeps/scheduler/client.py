"""Runs a sweep scheduler: wandb-core drives, this process optimizes.

The client initializes a scheduler session in wandb-core, builds the
optimizer from the sweep facts core returns, and exchanges tasks until the
scheduler is done.

Signals are handled here: only this process receives ctrl-c (wandb-core
runs in its own session), so the first one is translated into a graceful
stop request and the second one force-quits.
"""

from __future__ import annotations

import logging
import signal
from collections.abc import Callable
from typing import Any

import yaml

import wandb
from wandb.errors import term
from wandb.proto import wandb_sweep_scheduler_pb2 as sspb
from wandb.sdk import wandb_setup
from wandb.sdk.lib import wbauth
from wandb.sdk.sweeps.scheduler.ipc import (
    SchedulerTaskExchange,
    describe_done,
    forget_discards,
)
from wandb.sdk.sweeps.scheduler.optimizer import Optimizer
from wandb.sdk.sweeps.scheduler.run_logger import ControllerRunLogger
from wandb.sdk.sweeps.sweep_info import SweepInfo

# Init is one wandb-core round trip to the W&B backend, registering the
# scheduler and fetching the sweep's config, so allow for a slow network.
_INIT_TIMEOUT_SECONDS = 30

OptimizerFactory = Callable[[SweepInfo], Optimizer]
"""Builds the optimizer once the sweep's config is known."""


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

    try:
        init_response = singleton.asyncer.run(init)
    except Exception as e:
        term.termerror(f"Sweep scheduler for {sweep_id} failed to initialize: {e}")
        raise wandb.Error(f"The sweep scheduler failed to initialize: {e}") from e

    sweep = SweepInfo(
        id=sweep_id,
        name=init_response.display_name or sweep_id,
        entity=entity,
        project=project,
        config=yaml.safe_load(init_response.sweep_config) or {},
    )

    controller_run = _open_controller_run(
        entity=entity,
        project=project,
        run_name=init_response.controller_run_name,
    )
    try:
        with ControllerRunLogger(controller_run) as run_logger:
            return _execute_task_loop(
                singleton,
                service,
                init_response.session_id,
                sweep,
                make_optimizer,
                run_logger,
            )
    finally:
        # Finished after the logger closes, so the session's last lines
        # still reach the run.
        controller_run.finish()


def _open_controller_run(
    *,
    entity: str,
    project: str,
    run_name: str,
) -> wandb.Run:
    """Attach the sweep's controller run to collect this process's logs.

    Args:
        entity: The entity that owns the sweep.
        project: The project the sweep belongs to.
        run_name: The controller run's name.

    Returns:
        The attached run, to finish after the session.

    Raises:
        wandb.Error: If the run could not be attached.
    """
    try:
        return wandb.init(
            entity=entity,
            project=project,
            id=run_name,
            settings=wandb.Settings(
                # Console capture revises a line as
                # it is printed, so it would record partial lines.
                # ControllerRunLogger sends whole lines instead.
                console="off",
                silent=True,
                # The controller run outlives any one scheduler session,
                # so finishing it must not mark it complete.
                x_update_finish_state=False,
                # The run collects the sweep's scheduling history, not
                # facts about whichever machine hosts the scheduler, and
                # the server owns the rest of its metadata.
                x_disable_stats=True,
                x_disable_meta=True,
                x_disable_machine_info=True,
                x_save_requirements=False,
                x_label="sweep-scheduler",
            ),
        )
    except Exception as e:
        term.termerror(f"Sweep scheduler for {run_name} failed to log: {e}")
        raise wandb.Error(f"The sweep's controller run is unavailable: {e}") from e


def _execute_task_loop(
    singleton: Any,
    service: Any,
    scheduler_id: str,
    sweep: SweepInfo,
    make_optimizer: OptimizerFactory,
    run_logger: ControllerRunLogger,
) -> sspb.SweepSchedulerServerDoneTask:
    """Run the optimizer task exchange for one scheduler session.

    Args:
        singleton: The process's wandb setup singleton.
        service: The service connection to wandb-core.
        scheduler_id: The scheduler's id from the init response.
        sweep: The sweep being optimized.
        make_optimizer: Builds the optimizer from the sweep's facts.
        run_logger: Collects the sweep's logs for the controller run.

    Returns:
        The scheduler's Done task, describing why it stopped.

    Raises:
        wandb.Error: If the scheduler stopped because of a failure.
    """
    optimizer = make_optimizer(sweep)
    optimizer.attach_run_logger(run_logger)
    exchange = SchedulerTaskExchange(service, scheduler_id, optimizer)

    previous_handler = _install_sigint_handler(
        singleton.asyncer,
        service,
        scheduler_id,
    )
    restore_loggers = _capture_optimizer_loggers(optimizer, run_logger)
    try:
        done = singleton.asyncer.run(exchange.run)
    finally:
        restore_loggers()
        if previous_handler is not None:
            signal.signal(signal.SIGINT, previous_handler)

    forget_discards(optimizer, done)
    message, is_error = describe_done(done)
    if is_error:
        term.termerror(f"Sweep scheduler for {sweep.name} exited: {message}.")
        raise wandb.Error(f"The sweep scheduler failed: {message}.")

    term.termlog(f"Sweep scheduler for {sweep.name} exited: {message}.")
    return done


def _framework_label(optimizer: Optimizer) -> str:
    """The console label for the optimizer library's own log lines.

    Derived from the first captured logger's root name, which is the
    library's import name -- the name a user knows it by.
    """
    loggers = optimizer.captured_loggers()
    if not loggers:
        return ""
    return loggers[0].split(".")[0]


class _TermForwarder(logging.Handler):
    """Forwards a library logger's records to the terminal and the run."""

    def __init__(
        self,
        level: int,
        run_logger: ControllerRunLogger,
        label: str,
    ) -> None:
        super().__init__(level=level)
        self._run_logger = run_logger
        self._label = label

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._run_logger.log(
                f"{record.name}: {record.getMessage()}",
                label=self._label,
                level=record.levelno,
            )
        except Exception:
            self.handleError(record)


def _capture_optimizer_loggers(
    optimizer: Optimizer,
    run_logger: ControllerRunLogger,
) -> Callable[[], None]:
    """Surface the optimizer library's internal logging to the user.

    Optimizer libraries attach their own stream handlers, bound to the
    process's original stderr, which console capture cannot always see.
    For the session those handlers are swapped for a forwarder that
    echoes through term and appends to the controller run.

    Args:
        optimizer: The optimizer whose `captured_loggers` to hook.
        run_logger: Collects the sweep's logs for the controller run.

    Returns:
        A function undoing the swap.
    """
    forwarder = _TermForwarder(
        level=logging.INFO,
        run_logger=run_logger,
        label=_framework_label(optimizer),
    )

    hooked: list[logging.Logger] = []
    removed: list[tuple[logging.Logger, logging.Handler]] = []
    releveled: list[tuple[logging.Logger, int]] = []
    for name in optimizer.captured_loggers():
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            # Exact type: subclasses like FileHandler write elsewhere
            # and would not double the terminal output.
            if type(handler) is logging.StreamHandler:
                logger.removeHandler(handler)
                removed.append((logger, handler))
        logger.addHandler(forwarder)
        hooked.append(logger)

        # The forwarder only sees records the logger lets through. A
        # library that leaves its logger above INFO (or unset, inheriting
        # the root's WARNING) would drop the progress lines this capture
        # exists for, so pin the level for the session.
        if logger.getEffectiveLevel() > logging.INFO:
            releveled.append((logger, logger.level))
            logger.setLevel(logging.INFO)

    def restore() -> None:
        for logger in hooked:
            logger.removeHandler(forwarder)
        for logger, handler in removed:
            logger.addHandler(handler)
        for logger, level in releveled:
            logger.setLevel(level)

    return restore


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
