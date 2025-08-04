"""Abstract Scheduler class."""

import asyncio
import base64
import copy
import logging
import os
import socket
import threading
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Tuple, Union

import click
import yaml

import wandb
from wandb.errors import CommError
from wandb.sdk.launch._launch_add import launch_add
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.sweeps import SchedulerError
from wandb.sdk.launch.sweeps.utils import (
    create_sweep_command_args,
    make_launch_sweep_entrypoint,
)
from wandb.sdk.launch.utils import (
    event_loop_thread_exec,
    strip_resource_args_and_template_vars,
)
from wandb.sdk.lib.runid import generate_id

if TYPE_CHECKING:
    import wandb.apis.public as public
    from wandb.apis.internal import Api
    from wandb.apis.public import QueuedRun, Run


_logger = logging.getLogger(__name__)
LOG_PREFIX = f"{click.style('sched:', fg='cyan')} "

DEFAULT_POLLING_SLEEP = 5.0


class SchedulerState(Enum):
    PENDING = 0
    STARTING = 1
    RUNNING = 2
    FLUSH_RUNS = 3
    COMPLETED = 4
    FAILED = 5
    STOPPED = 6
    CANCELLED = 7


class RunState(Enum):
    RUNNING = "running", "alive"
    PENDING = "pending", "alive"
    PREEMPTING = "preempting", "alive"
    CRASHED = "crashed", "dead"
    FAILED = "failed", "dead"
    KILLED = "killed", "dead"
    FINISHED = "finished", "dead"
    PREEMPTED = "preempted", "dead"
    # unknown when api.get_run_state fails or returns unexpected state
    # assumed alive, unless we get unknown 2x then move to failed (dead)
    UNKNOWN = "unknown", "alive"

    def __new__(cls: Any, *args: List, **kwds: Any) -> "RunState":
        obj: RunState = object.__new__(cls)
        obj._value_ = args[0]
        return obj

    def __init__(self, _: str, life: str = "unknown") -> None:
        self._life = life

    @property
    def is_alive(self) -> bool:
        return self._life == "alive"


@dataclass
class _Worker:
    agent_config: Dict[str, Any]
    agent_id: str


@dataclass
class SweepRun:
    id: str
    worker_id: int
    state: RunState = RunState.RUNNING
    queued_run: Optional["public.QueuedRun"] = None
    args: Optional[Dict[str, Any]] = None
    logs: Optional[List[str]] = None


class Scheduler(ABC):
    """A controller/agent that populates a Launch RunQueue from a hyperparameter sweep."""

    PLACEHOLDER_URI = "placeholder-uri-scheduler"
    SWEEP_JOB_TYPE = "sweep-controller"
    ENTRYPOINT = ["wandb", "scheduler", "WANDB_SWEEP_ID"]

    def __init__(
        self,
        api: "Api",
        *args: Optional[Any],
        polling_sleep: Optional[float] = None,
        sweep_id: Optional[str] = None,
        entity: Optional[str] = None,
        project: Optional[str] = None,
        project_queue: Optional[str] = None,
        num_workers: Optional[Union[int, str]] = None,
        **kwargs: Optional[Any],
    ):
        from wandb.apis.public import Api as PublicApi

        self._api = api
        self._public_api = PublicApi()
        self._entity = (
            entity
            or os.environ.get("WANDB_ENTITY")
            or api.settings("entity")
            or api.default_entity
        )
        self._project = (
            project or os.environ.get("WANDB_PROJECT") or api.settings("project")
        )
        self._sweep_id: str = sweep_id or "empty-sweep-id"
        self._state: SchedulerState = SchedulerState.PENDING

        # Make sure the provided sweep_id corresponds to a valid sweep
        try:
            resp = self._api.sweep(
                sweep_id, "{}", entity=self._entity, project=self._project
            )
            if resp.get("state") == SchedulerState.CANCELLED.name:
                self._state = SchedulerState.CANCELLED
            self._sweep_config = yaml.safe_load(resp["config"])
            self._num_runs_launched: int = self._get_num_runs_launched(resp["runs"])
            if self._num_runs_launched > 0:
                wandb.termlog(
                    f"{LOG_PREFIX}Found {self._num_runs_launched} previous valid runs for sweep {self._sweep_id}"
                )
        except Exception as e:
            raise SchedulerError(
                f"{LOG_PREFIX}Exception when finding sweep ({sweep_id}) {e}"
            )

        # Scheduler may receive additional kwargs which will be piped into the launch command
        self._kwargs: Dict[str, Any] = kwargs

        # Dictionary of the runs being managed by the scheduler
        self._runs: Dict[str, SweepRun] = {}
        # Threading lock to ensure thread-safe access to the runs dictionary
        self._threading_lock: threading.Lock = threading.Lock()
        self._polling_sleep = (
            polling_sleep if polling_sleep is not None else DEFAULT_POLLING_SLEEP
        )
        self._project_queue = project_queue
        # Optionally run multiple workers in (pseudo-)parallel. Workers do not
        # actually run training workloads, they simply send heartbeat messages
        # (emulating a real agent) and add new runs to the launch queue. The
        # launch agent is the one that actually runs the training workloads.
        self._workers: Dict[int, _Worker] = {}

        # Init wandb scheduler run
        self._wandb_run = self._init_wandb_run()

        # Grab params from scheduler wandb run config
        num_workers = num_workers or self._wandb_run.config.get("scheduler", {}).get(
            "num_workers"
        )
        self._num_workers = int(num_workers) if str(num_workers).isdigit() else 8
        self._settings_config: Dict[str, Any] = self._wandb_run.config.get(
            "settings", {}
        )

    @abstractmethod
    def _get_next_sweep_run(self, worker_id: int) -> Optional[SweepRun]:
        """Called when worker available."""

    @abstractmethod
    def _poll(self) -> None:
        """Called every polling loop."""

    @abstractmethod
    def _exit(self) -> None:
        pass

    @abstractmethod
    def _load_state(self) -> None:
        pass

    @abstractmethod
    def _save_state(self) -> None:
        pass

    @property
    def state(self) -> SchedulerState:
        _logger.debug(f"{LOG_PREFIX}Scheduler state is {self._state.name}")
        return self._state

    @state.setter
    def state(self, value: SchedulerState) -> None:
        _logger.debug(f"{LOG_PREFIX}Scheduler was {self.state.name} is {value.name}")
        self._state = value

    @property
    def is_alive(self) -> bool:
        if self.state in [
            SchedulerState.COMPLETED,
            SchedulerState.FAILED,
            SchedulerState.STOPPED,
            SchedulerState.CANCELLED,
        ]:
            return False
        return True

    @property
    def at_runcap(self) -> bool:
        """False if under user-specified cap on # of runs."""
        run_cap = self._sweep_config.get("run_cap")
        if not run_cap:
            return False
        at_runcap: bool = self._num_runs_launched >= run_cap
        return at_runcap

    @property
    def num_active_runs(self) -> int:
        return len(self._runs)

    @property
    def busy_workers(self) -> Dict[int, _Worker]:
        """Returns dict of id:worker already assigned to a launch run.

        runs should always have a worker_id, but are created before
        workers are assigned to the run
        """
        busy_workers = {}
        for _, r in self._yield_runs():
            busy_workers[r.worker_id] = self._workers[r.worker_id]
        return busy_workers

    @property
    def available_workers(self) -> Dict[int, _Worker]:
        """Returns dict of id:worker ready to launch another run."""
        if len(self._workers) == 0:
            return {}
        return {
            _id: w for _id, w in self._workers.items() if _id not in self.busy_workers
        }

    def _init_wandb_run(self) -> "wandb.Run":
        """Controls resume or init logic for a scheduler wandb run."""
        settings = wandb.Settings(disable_job_creation=True)
        run: wandb.Run = wandb.init(  # type: ignore
            name=f"Scheduler.{self._sweep_id}",
            resume="allow",
            config=self._kwargs,  # when run as a job, this sets config
            settings=settings,
        )
        return run

    def stop_sweep(self) -> None:
        """Stop the sweep."""
        self._state = SchedulerState.STOPPED

    def fail_sweep(self, err: Optional[str]) -> None:
        """Fail the sweep w/ optional exception."""
        self._state = SchedulerState.FAILED
        if err:
            raise SchedulerError(err)

    def start(self) -> None:
        """Start a scheduler, confirms prerequisites, begins execution loop."""
        wandb.termlog(f"{LOG_PREFIX}Scheduler starting.")
        if not self.is_alive:
            wandb.termerror(
                f"{LOG_PREFIX}Sweep already in end state ({self.state.name.lower()}). Exiting..."
            )
            self.exit()
            return

        self._state = SchedulerState.STARTING
        if not self._try_load_executable():
            wandb.termerror(
                f"{LOG_PREFIX}No 'job' or 'image_uri' loaded from sweep config."
            )
            self.exit()
            return

        # For resuming sweeps
        self._load_state()
        asyncio.run(self._register_agents())
        self.run()

    def run(self) -> None:
        """Main run function."""
        wandb.termlog(f"{LOG_PREFIX}Scheduler running")
        self.state = SchedulerState.RUNNING
        try:
            while True:
                self._update_scheduler_run_state()
                if not self.is_alive:
                    break

                wandb.termlog(f"{LOG_PREFIX}Polling for new runs to launch")

                self._update_run_states()
                self._poll()
                if self.state == SchedulerState.FLUSH_RUNS:
                    if self.num_active_runs == 0:
                        wandb.termlog(f"{LOG_PREFIX}Done polling on runs, exiting")
                        break
                    time.sleep(self._polling_sleep)
                    continue

                for worker_id in self.available_workers:
                    if self.at_runcap:
                        wandb.termlog(
                            f"{LOG_PREFIX}Sweep at run_cap ({self._num_runs_launched})"
                        )
                        self.state = SchedulerState.FLUSH_RUNS
                        break

                    try:
                        run: Optional[SweepRun] = self._get_next_sweep_run(worker_id)
                        if not run:
                            break
                    except SchedulerError as e:
                        raise SchedulerError(e)
                    except Exception as e:
                        wandb.termerror(
                            f"{LOG_PREFIX}Failed to get next sweep run: {e}"
                        )
                        self.state = SchedulerState.FAILED
                        break

                    if self._add_to_launch_queue(run):
                        self._num_runs_launched += 1

                time.sleep(self._polling_sleep)
        except KeyboardInterrupt:
            wandb.termwarn(f"{LOG_PREFIX}Scheduler received KeyboardInterrupt. Exiting")
            self.state = SchedulerState.STOPPED
            self.exit()
            return
        except Exception as e:
            wandb.termlog(f"{LOG_PREFIX}Scheduler failed with exception {e}")
            self.state = SchedulerState.FAILED
            self.exit()
            raise
        else:
            # scheduler succeeds if at runcap
            if self.state == SchedulerState.FLUSH_RUNS and self.at_runcap:
                self.state = SchedulerState.COMPLETED
            self.exit()

    def exit(self) -> None:
        self._exit()
        # _save_state isn't controlled, possibly fails
        try:
            self._save_state()
        except Exception:
            wandb.termerror(
                f"{LOG_PREFIX}Failed to save state: {traceback.format_exc()}"
            )

        status = ""
        if self.state == SchedulerState.FLUSH_RUNS:
            self._set_sweep_state("PAUSED")
            status = "paused"
        elif self.state == SchedulerState.COMPLETED:
            self._set_sweep_state("FINISHED")
            status = "completed"
        elif self.state in [SchedulerState.CANCELLED, SchedulerState.STOPPED]:
            self._set_sweep_state("CANCELED")  # one L
            status = "cancelled"
            self._stop_runs()
        else:
            self.state = SchedulerState.FAILED
            self._set_sweep_state("CRASHED")
            status = "crashed"
            self._stop_runs()

        wandb.termlog(f"{LOG_PREFIX}Scheduler {status}")
        self._wandb_run.finish()

    def _get_num_runs_launched(self, runs: List[Dict[str, Any]]) -> int:
        """Returns the number of valid runs in the sweep."""
        count = 0
        for run in runs:
            # if bad run, shouldn't be counted against run cap
            if run.get("state", "") in ["killed", "crashed"] and not run.get(
                "summaryMetrics"
            ):
                _logger.debug(
                    f"excluding run: {run['name']} with state: {run['state']} from run cap \n{run}"
                )
                continue
            count += 1

        return count

    def _try_load_executable(self) -> bool:
        """Check existence of valid executable for a run.

        logs and returns False when job is unreachable
        """
        if self._kwargs.get("job"):
            try:
                _job_artifact = self._public_api.job(self._kwargs["job"])
                wandb.termlog(
                    f"{LOG_PREFIX}Successfully loaded job ({_job_artifact.name}) in scheduler"
                )
            except Exception:
                wandb.termerror(f"{LOG_PREFIX}{traceback.format_exc()}")
                return False
            return True
        elif self._kwargs.get("image_uri"):
            # TODO(gst): check docker existence? Use registry in launch config?
            return True
        else:
            return False

    async def _register_agents(self) -> None:
        tasks = []
        register_agent = event_loop_thread_exec(self._api.register_agent)
        for worker_id in range(self._num_workers):
            _logger.debug(f"{LOG_PREFIX}Starting AgentHeartbeat worker ({worker_id})")
            try:
                worker = register_agent(
                    f"{socket.gethostname()}-{worker_id}",  # host
                    sweep_id=self._sweep_id,
                    project_name=self._project,
                    entity=self._entity,
                )
                tasks.append(worker)
            except Exception as e:
                _logger.debug(f"failed to register agent: {e}")
                self.fail_sweep(f"failed to register agent: {e}")

        finished_tasks = await asyncio.gather(*tasks)
        for idx, agent_config in enumerate(finished_tasks):
            self._workers[idx] = _Worker(
                agent_config=agent_config,
                agent_id=agent_config["id"],
            )

    def _yield_runs(self) -> Iterator[Tuple[str, SweepRun]]:
        """Thread-safe way to iterate over the runs."""
        with self._threading_lock:
            yield from self._runs.items()

    def _cleanup_runs(self, runs_to_remove: List[str]) -> None:
        """Helper for removing runs from memory.

        Can be overloaded to prevent deletion of runs, which is useful
        for debugging or when polling on completed runs.
        """
        with self._threading_lock:
            for run_id in runs_to_remove:
                wandb.termlog(f"{LOG_PREFIX}Cleaning up finished run ({run_id})")
                del self._runs[run_id]

    def _stop_runs(self) -> None:
        to_delete = []
        for run_id, _ in self._yield_runs():
            to_delete += [run_id]

        for run_id in to_delete:
            wandb.termlog(f"{LOG_PREFIX}Stopping run ({run_id})")
            if not self._stop_run(run_id):
                wandb.termwarn(f"{LOG_PREFIX}Failed to stop run ({run_id})")

    def _stop_run(self, run_id: str) -> bool:
        """Stops a run and removes it from the scheduler."""
        if run_id not in self._runs:
            _logger.debug(f"run: {run_id} not in _runs: {self._runs}")
            return False

        run = self._runs[run_id]
        del self._runs[run_id]

        if not run.queued_run:
            _logger.debug(
                f"tried to _stop_run but run not queued yet (run_id:{run.id})"
            )
            return False

        if not run.state.is_alive:
            # run already dead, just delete reference
            return True

        # run still alive, send stop signal
        encoded_run_id = base64.standard_b64encode(
            f"Run:v1:{run_id}:{self._project}:{self._entity}".encode()
        ).decode("utf-8")

        try:
            success: bool = self._api.stop_run(run_id=encoded_run_id)
            if success:
                wandb.termlog(f"{LOG_PREFIX}Stopped run {run_id}.")
                return True
        except Exception as e:
            _logger.debug(f"error stopping run ({run_id}): {e}")

        return False

    def _update_scheduler_run_state(self) -> None:
        """Update the scheduler state from state of scheduler run and sweep state."""
        state: RunState = self._get_run_state(self._wandb_run.id)

        # map scheduler run-state to scheduler-state
        if state == RunState.KILLED:
            self.state = SchedulerState.STOPPED
        elif state in [RunState.FAILED, RunState.CRASHED]:
            self.state = SchedulerState.FAILED
        elif state == RunState.FINISHED:
            self.state = SchedulerState.COMPLETED

        # check sweep state for completed states, overwrite scheduler state
        try:
            sweep_state = self._api.get_sweep_state(
                self._sweep_id, self._entity, self._project
            )
        except Exception as e:
            _logger.debug(f"sweep state error: {e}")
            return

        if sweep_state == "FINISHED":
            self.state = SchedulerState.COMPLETED
        elif sweep_state in ["CANCELLED", "STOPPED"]:
            self.state = SchedulerState.CANCELLED
        elif sweep_state == "PAUSED":
            self.state = SchedulerState.FLUSH_RUNS

    def _update_run_states(self) -> None:
        """Iterate through runs.

        Get state from backend and deletes runs if not in running state. Threadsafe.
        """
        runs_to_remove: List[str] = []
        for run_id, run in self._yield_runs():
            run.state = self._get_run_state(run_id, run.state)

            try:
                rqi_state = run.queued_run.state if run.queued_run else None
            except (CommError, LaunchError) as e:
                _logger.debug(f"Failed to get queued_run.state: {e}")
                rqi_state = None

            if not run.state.is_alive or rqi_state == "failed":
                _logger.debug(f"({run_id}) states: ({run.state}, {rqi_state})")
                runs_to_remove.append(run_id)
        self._cleanup_runs(runs_to_remove)

    def _get_metrics_from_run(self, run_id: str) -> List[Any]:
        """Use the public api to get metrics from a run.

        Uses the metric name found in the sweep config, any
        misspellings will result in an empty list.
        """
        try:
            queued_run: Optional[QueuedRun] = self._runs[run_id].queued_run
            if not queued_run:
                return []

            api_run: Run = self._public_api.run(
                f"{queued_run.entity}/{queued_run.project}/{run_id}"
            )
            metric_name = self._sweep_config["metric"]["name"]
            history = api_run.scan_history(keys=["_step", metric_name])
            metrics = [x[metric_name] for x in history]

            return metrics
        except Exception as e:
            _logger.debug(f"[_get_metrics_from_run] {e}")
        return []

    def _get_run_info(self, run_id: str) -> Dict[str, Any]:
        """Use the public api to get info about a run."""
        try:
            info: Dict[str, Any] = self._api.get_run_info(
                self._entity, self._project, run_id
            )
            if info:
                return info
        except Exception as e:
            _logger.debug(f"[_get_run_info] {e}")
        return {}

    def _get_run_state(
        self, run_id: str, prev_run_state: RunState = RunState.UNKNOWN
    ) -> RunState:
        """Use the public api to get state of a run."""
        run_state = None
        try:
            state = self._api.get_run_state(self._entity, self._project, run_id)
            run_state = RunState(state)
        except CommError as e:
            _logger.debug(f"error getting state for run ({run_id}): {e}")
            if prev_run_state == RunState.UNKNOWN:
                # triggers when we get an unknown state for the second time
                wandb.termwarn(
                    f"Failed to get runstate for run ({run_id}). Error: {traceback.format_exc()}"
                )
                run_state = RunState.FAILED
            else:  # first time we get unknown state
                run_state = RunState.UNKNOWN
        except (AttributeError, ValueError):
            wandb.termwarn(
                f"Bad state ({run_state}) for run ({run_id}). Error: {traceback.format_exc()}"
            )
            run_state = RunState.UNKNOWN
        return run_state

    def _create_run(self) -> Dict[str, Any]:
        """Use the public api to create a blank run."""
        try:
            run: List[Dict[str, Any]] = self._api.upsert_run(
                project=self._project,
                entity=self._entity,
                sweep_name=self._sweep_id,
            )
            if run:
                return run[0]
        except Exception as e:
            _logger.debug(f"[_create_run] {e}")
            raise SchedulerError(
                "Error creating run from scheduler, check API connection and CLI version."
            )
        return {}

    def _set_sweep_state(self, state: str) -> None:
        wandb.termlog(f"{LOG_PREFIX}Updating sweep state to: {state.lower()}")
        try:
            self._api.set_sweep_state(sweep=self._sweep_id, state=state)
        except Exception as e:
            _logger.debug(f"[set_sweep_state] {e}")

    def _encode(self, _id: str) -> str:
        return (
            base64.b64decode(bytes(_id.encode("utf-8"))).decode("utf-8").split(":")[2]
        )

    def _make_entry_and_launch_config(
        self, run: SweepRun
    ) -> Tuple[Optional[List[str]], Dict[str, Dict[str, Any]]]:
        args = create_sweep_command_args({"args": run.args})
        entry_point, macro_args = make_launch_sweep_entrypoint(
            args, self._sweep_config.get("command")
        )
        # handle program macro
        if entry_point and "${program}" in entry_point:
            if not self._sweep_config.get("program"):
                raise SchedulerError(
                    f"{LOG_PREFIX}Program macro in command has no corresponding 'program' in sweep config."
                )
            pidx = entry_point.index("${program}")
            entry_point[pidx] = self._sweep_config["program"]

        launch_config = copy.deepcopy(self._wandb_run.config.get("launch", {}))
        if "overrides" not in launch_config:
            launch_config["overrides"] = {"run_config": {}}
        if "run_config" not in launch_config["overrides"]:
            launch_config["overrides"]["run_config"] = {}
        launch_config["overrides"]["run_config"].update(args["args_dict"])

        if macro_args:  # pipe in hyperparam args as params to launch
            launch_config["overrides"]["args"] = macro_args

        if entry_point:
            unresolved = [x for x in entry_point if str(x).startswith("${")]
            if unresolved:
                wandb.termwarn(
                    f"{LOG_PREFIX}Sweep command contains unresolved macros: "
                    f"{unresolved}, see launch docs for supported macros."
                )
        return entry_point, launch_config

    def _add_to_launch_queue(self, run: SweepRun) -> bool:
        """Convert a sweeprun into a launch job then push to runqueue."""
        # job and image first from CLI args, then from sweep config
        _job = self._kwargs.get("job") or self._sweep_config.get("job")
        _sweep_config_uri = self._sweep_config.get("image_uri")
        _image_uri = self._kwargs.get("image_uri") or _sweep_config_uri
        if _job is None and _image_uri is None:
            raise SchedulerError(f"{LOG_PREFIX}No 'job' nor 'image_uri' ({run.id})")
        elif _job is not None and _image_uri is not None:
            raise SchedulerError(f"{LOG_PREFIX}Sweep has both 'job' and 'image_uri'")

        entry_point, launch_config = self._make_entry_and_launch_config(run)
        if entry_point:
            wandb.termwarn(
                f"{LOG_PREFIX}Sweep command {entry_point} will override"
                f" {'job' if _job else 'image_uri'} entrypoint"
            )

        # override resource and args of job
        _job_launch_config = copy.deepcopy(self._wandb_run.config.get("launch")) or {}

        # default priority is "medium"
        _priority = int(launch_config.get("priority", 2))  # type: ignore

        # strip resource_args and template_variables from launch_config
        strip_resource_args_and_template_vars(_job_launch_config)

        run_id = run.id or generate_id()
        queued_run = launch_add(
            run_id=run_id,
            entry_point=entry_point,
            config=launch_config,
            docker_image=_image_uri,  # TODO(gst): make agnostic (github? run uri?)
            job=_job,
            project=self._project,
            entity=self._entity,
            queue_name=self._kwargs.get("queue"),
            project_queue=self._project_queue,
            resource=_job_launch_config.get("resource"),
            resource_args=_job_launch_config.get("resource_args"),
            template_variables=_job_launch_config.get("template_variables"),
            author=self._kwargs.get("author"),
            sweep_id=self._sweep_id,
            priority=_priority,
        )
        run.queued_run = queued_run
        # TODO(gst): unify run and queued_run state
        run.state = RunState.RUNNING  # assume it will get picked up
        self._runs[run_id] = run

        wandb.termlog(
            f"{LOG_PREFIX}Added run ({run_id}) to queue ({self._kwargs.get('queue')})"
        )
        return True
