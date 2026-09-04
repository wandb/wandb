"""Runs a sweep scheduler: wandb-core drives, this process optimizes.

The client initializes a scheduler session in wandb-core, builds the
optimizer from the sweep facts core returns, and exchanges tasks until the
scheduler is done. When the sweep has a controller run, the host attaches
it like any other run, so console capture streams everything this process
prints — status lines and Optimizer.log() output — to the run.

Signals are handled here: only this process receives ctrl-c (wandb-core
runs in its own session), so the first one is translated into a graceful
stop request and the second one force-quits.
"""

from __future__ import annotations

import logging
import signal
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import yaml

import wandb
from wandb.errors import term
from wandb.proto import wandb_sweep_scheduler_pb2 as sspb
from wandb.sdk import wandb_setup
from wandb.sdk.lib import console_capture, wbauth
from wandb.sdk.sweeps.scheduler.ipc import (
    SchedulerTaskExchange,
    describe_done,
    forget_discards,
)
from wandb.sdk.sweeps.scheduler.optimizer import Optimizer
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

    controller_run = _open_controller_run(
        entity=entity,
        project=project,
        run_name=init_response.controller_run_name,
    )
    try:
        return _execute_task_loop(
            singleton,
            service,
            init_response.session_id,
            sweep,
            make_optimizer,
            controller_run,
        )
    finally:
        # Finished last so the session's exit message is captured too.
        # This never marks the controller run complete; see
        # _open_controller_run.
        if controller_run is not None:
            controller_run.finish()


def _open_controller_run(
    *,
    entity: str,
    project: str,
    run_name: str,
) -> wandb.Run | None:
    """Attach the sweep's controller run to collect this process's console.

    The controller run is created server-side. Attaching it through the
    regular runs system streams everything this process prints from here
    on to the run as console logs; the backend orders log lines from the
    sweep's several writers.

    A failed attach costs log lines, never the sweep: errors are reported
    and swallowed.

    Args:
        entity: The entity that owns the sweep.
        project: The project the sweep belongs to.
        run_name: The controller run's name; empty when the sweep has none.

    Returns:
        The run whose console capture is active, to finish after the
        session, or None when the sweep has no controller run or the
        attach failed.
    """
    if not run_name:
        return None

    try:
        run = wandb.init(
            entity=entity,
            project=project,
            id=run_name,
            settings=wandb.Settings(
                # The attachment is scheduler plumbing: its sync banners
                # ("Syncing run ...", "View run at ...") would only tell
                # the user about a run they did not start. Scoped to this
                # attachment; the process's own output is unaffected.
                silent=True,
                # The controller run outlives any one scheduler session,
                # so finishing it must not mark it complete.
                x_update_finish_state=False,
                # The run collects the sweep's scheduling history, not
                # facts about whichever machine hosts the scheduler.
                x_disable_stats=True,
                x_disable_meta=True,
                x_label="sweep-scheduler",
                # The sweep's log store appends console updates rather
                # than overwriting them by offset, so a partially
                # flushed line must never be streamed.
                x_console_complete_lines=True,
            ),
        )
    except Exception as e:
        term.termwarn(f"Scheduler logs will only reach the terminal: {e}")
        return None

    return run


def _execute_task_loop(
    singleton: Any,
    service: Any,
    scheduler_id: str,
    sweep: SweepInfo,
    make_optimizer: OptimizerFactory,
    controller_run: wandb.Run | None,
) -> sspb.SweepSchedulerServerDoneTask:
    """Run the optimizer task exchange for one scheduler session.

    Args:
        singleton: The process's wandb setup singleton.
        service: The service connection to wandb-core.
        scheduler_id: The scheduler's id from the init response.
        sweep: The sweep being optimized.
        make_optimizer: Builds the optimizer from the sweep's facts.
        controller_run: The attached run collecting the sweep's logs, or
            None when the sweep has none or the attach failed.

    Returns:
        The scheduler's Done task, describing why it stopped.

    Raises:
        wandb.Error: If the scheduler stopped because of a failure.
    """
    optimizer = make_optimizer(sweep)
    optimizer.attach_controller_run(controller_run)
    exchange = SchedulerTaskExchange(service, scheduler_id, optimizer)

    previous_handler = _install_sigint_handler(
        singleton.asyncer,
        service,
        scheduler_id,
    )
    restore_loggers = _capture_optimizer_loggers(optimizer, controller_run)
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
    """Forwards a library logger's records to the terminal and controller run.

    The controller run copy goes through `run.write_logs` under the
    library's own label, so the backend attributes the lines to the
    library instead of the scheduler; the terminal echo hides from
    console capture so the run does not also record a scheduler-labeled
    copy. Without a controller run, the echo is captured like any other
    console line.
    """

    def __init__(
        self,
        level: int,
        controller_run: wandb.Run | None,
        label: str,
    ) -> None:
        super().__init__(level=level)
        self._controller_run = controller_run
        self._label = label

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = f"{record.name}: {record.getMessage()}"
            if record.levelno >= logging.ERROR:
                log_to_term = term.termerror
            elif record.levelno >= logging.WARNING:
                log_to_term = term.termwarn
            else:
                log_to_term = term.termlog

            if self._controller_run is None:
                log_to_term(message)
                return

            with console_capture.uncaptured():
                log_to_term(message)
            # term renders the severity on the terminal; the run copy
            # spells it out itself.
            if record.levelno >= logging.WARNING:
                message = f"{record.levelname} {message}"
            self._controller_run.write_logs(message, label=self._label)
        except Exception:
            self.handleError(record)


def _capture_optimizer_loggers(
    optimizer: Optimizer,
    controller_run: wandb.Run | None,
) -> Callable[[], None]:
    """Surface the optimizer library's internal logging to the user.

    Optimizer libraries attach their own stream handlers, bound to the
    process's original stderr, which console capture cannot always see.
    For the session those handlers are swapped for a forwarder that
    echoes through term and writes to the controller run under the
    library's own label, so the lines reach the terminal and the run
    exactly once.

    Args:
        optimizer: The optimizer whose `captured_loggers` to hook.
        controller_run: The attached run collecting the sweep's logs, or
            None when the sweep has none or the attach failed.

    Returns:
        A function undoing the swap.
    """
    forwarder = _TermForwarder(
        level=logging.INFO,
        controller_run=controller_run,
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
