from collections import defaultdict
import logging
import pprint
import queue
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import optuna

import wandb
from wandb.sdk.launch.sweeps import SchedulerError
from wandb.sdk.launch.sweeps.scheduler import (
    LOG_PREFIX,
    Scheduler,
    SchedulerState,
    SimpleRunState,
    SweepRun,
)
from wandb.wandb_agent import Agent as LegacySweepAgent

from wandb.apis.public import QueuedRun, Api as PublicApi
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb_run import Run

logger = logging.getLogger(__name__)


@dataclass
class _Worker:
    agent_config: Dict[str, Any]
    agent_id: str


class OptunaScheduler(Scheduler):
    def __init__(
        self,
        *args: Any,
        num_workers: int = 8,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self._workers: Dict[int, _Worker] = {}
        self._num_workers: int = num_workers

        self._public_api = PublicApi()

        self.study: optuna.study.Study = None
        self._trial_func = None
        self._storage_name = ""
        self._artifact_name = "optuna-scheduler"

        wandb.log("Creating scheduler wandb run")
        self._wandb_run: Run = wandb.init(name=f"sweep-scheduler-{self._sweep_id}")
        self._load_db()

    def _load_db(self):
        """
        Create an optuna study with a sqlite backened for loose state management
        """
        # TODO(gst): add to validate function to confirm this exists, warn user
        if not self._study_name:
            self._study_name = f"optuna-study-{self._sweep_id}"

        params = self._sweep_config.get("parameters", {})
        if params.get("objective_func"):
            artifact = self._wandb_run.use_artifact("optuna-objective")
            if artifact:
                wandb.termlog(f"{LOG_PREFIX}Downloaded objective: {artifact}")
                path = artifact.get_path("objective.py")
                path.download()

                try:
                    from objective import objective
                except Exception as e:
                    wandb.termwarn(f"failed to load objective function: {str(e)}")
                    raise e

                self._objective = objective

            else:
                wandb.termlog(
                    f"{LOG_PREFIX}Failed to load objective: {params.get('objective_func')}"
                )

            self._trial_func = self._make_trial_from_objective
        else:
            self._trial_func = self._make_trial

        pruner_args = params.get("pruner", {})
        pruner = self._make_optuna_pruner(pruner_args)

        if self._wandb_run.resumed:
            # our scheduler was resumed, try to load state
            storage = self._wandb_run.use_artifact(self._artifact_name)
            storage.download()
            self._storage_name = storage
        else:
            self._storage_name = f"{self._study_name}.db"

        self.study = optuna.create_study(
            study_name=self._study_name,
            storage=f"sqlite:///{self._storage_name}",
            pruner=pruner,
            load_if_exists=True,
        )

    def _save_scheduler_state(self) -> None:
        scheduler_artifact = wandb.Artifact(self._artifact_name, type="scheduler")
        scheduler_artifact.add_file(f".{self._storage_name}")
        self._wandb_run.log_artifact(scheduler_artifact)

    def _start(self) -> None:
        for worker_id in range(self._num_workers):
            logger.debug(f"{LOG_PREFIX}Starting AgentHeartbeat worker {worker_id}\n")
            agent_config = self._api.register_agent(
                f"{socket.gethostname()}-{worker_id}",  # host
                sweep_id=self._sweep_id,
                project_name=self._project,
                entity=self._entity,
            )
            self._workers[worker_id] = _Worker(
                agent_config=agent_config,
                agent_id=agent_config["id"],
            )

    def _heartbeat(self, worker_id: int) -> None:
        # Make sure Scheduler is alive
        if not self.is_alive():
            return
        # AgentHeartbeat wants a Dict of runs which are running or queued
        _run_states: Dict[str, bool] = {}
        for run_id, run in self._yield_runs():
            # Filter out runs that are from a different worker thread
            if run.worker_id == worker_id and run.state == SimpleRunState.ALIVE:
                _run_states[run_id] = True
        logger.debug(
            f"{LOG_PREFIX}AgentHeartbeat sending: \n{pprint.pformat(_run_states)}\n"
        )
        commands: List[Dict[str, Any]] = self._api.agent_heartbeat(
            self._workers[worker_id].agent_id,  # agent_id: str
            {},  # metrics: dict
            _run_states,  # run_states: dict
        )
        logger.debug(
            f"{LOG_PREFIX}AgentHeartbeat received {len(commands)} commands: \n{pprint.pformat(commands)}\n"
        )
        if commands:
            for command in commands:
                # The command "type" can be one of "run", "resume", "stop", "exit"
                _type = command.get("type", None)
                if _type in ["exit", "stop"]:
                    # Tell (virtual) agent to stop running
                    self.state = SchedulerState.STOPPED
                    self.exit()
                    return
                elif _type in ["run", "resume"]:
                    _run_id = command.get("run_id", None)
                    if _run_id is None:
                        self.state = SchedulerState.FAILED
                        raise SchedulerError(
                            f"AgentHeartbeat command {command} missing run_id"
                        )
                    if _run_id in self._runs:
                        wandb.termlog(f"{LOG_PREFIX} Skipping duplicate run {run_id}")
                    else:
                        program = command.get("program")
                        if not program:
                            self._sweep_config.get("program")

                        config, trial = self._trial_func()
                        run = SweepRun(
                            id=_run_id,
                            args=config,
                            logs=command.get("logs", []),
                            program=program,
                            worker_id=worker_id,
                        )
                        self._run_trials[run.id] = trial
                        self._runs[run.id] = run
                        self._job_queue.put(run)
                else:
                    self.state = SchedulerState.FAILED
                    raise SchedulerError(f"AgentHeartbeat unknown command type {_type}")

    def _run(self) -> None:
        """
        Poll currently known runs for new metrics
        report new metrics to optuna
        send kill signals to existing runs if pruned
        hearbeat workers with backend
        create new runs if necessary from optuna suggestions
        launch new runs
        """
        pruned = self._poll_running_runs()
        for run in pruned:
            self._stop_run(run.id)

        for worker_id in self._workers:
            self._heartbeat(worker_id)
        try:
            srun: SweepRun = self._job_queue.get(timeout=self._queue_timeout)
        except queue.Empty:
            wandb.termlog(f"{LOG_PREFIX}No jobs in Sweeps RunQueue, waiting...")
            time.sleep(self._queue_sleep)
            return

        # If run is already stopped just ignore the request
        if srun.state in [
            SimpleRunState.DEAD,
            SimpleRunState.UNKNOWN,
        ]:
            return

        wandb.termlog(
            f"{LOG_PREFIX}Converting Sweep Run (RunID:{srun.id}) to Launch Job"
        )

        # send to launch
        self._add_to_launch_queue(
            run_id=srun.id,
            entry_point=[f"WANDB_SWEEP_ID={self._sweep_id} python3", srun.program]
            if srun.program
            else None,
            # Use legacy sweep utilities to extract args dict from agent heartbeat run.args
            config={
                "overrides": {
                    "run_config": LegacySweepAgent._create_command_args(
                        {"args": srun.args}
                    )["args_dict"]
                }
            },
        )

    def _get_run_history(self, run_id):
        # wait for launch to actually create a run object
        queued_run = self._runs[run_id].queued_run
        launched_run = queued_run.wait_until_running()
        launched_run_path = "/".join(launched_run.path)

        api_run: Run = self._public_api.run(launched_run_path)
        metric_name = self._sweep_config["metric"]["name"]
        history = api_run.scan_history(keys=["_step", metric_name])

        finished = api_run.state == "finished"

        return [x[metric_name] for x in history], finished

    def _poll_running_runs(self):
        for run, trial in self._run_trials.items():
            # poll metrics, feed into optuna
            metrics, run_finished = self.api.get_run_metric_history(run.id)
            last_metric__idx = self._metric_history[run.id]
            for i, metric in enumerate(metrics[last_metric__idx:]):
                trial = self._run_trials[run.id]
                trial.report(metric, last_metric__idx + i)
                self._metric_history[run.id] = len(metrics) - 1

                # ask optuna if we should prune the run
                if trial.should_prune():
                    print(f"{LOG_PREFIX}Optuna decided to PRUNE!")
                    self._stop_run(run.id)
                    self.study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                    break

            if run_finished:
                self.study.tell(trial, metrics[-1])

    def _make_trial(self, *args):
        trial = self.study.ask()
        config = defaultdict(dict)
        for param, extras in self._sweep_config["parameters"].items():
            if values := extras.get("values"):  # categorical
                config[param]["value"] = trial.suggest_categorical(param, values)
            elif value := extras.get("value"):
                config[param]["value"] = trial.suggest_categorical(param, [value])
            elif type(extras.get("min")) == float:
                log = "log" in param
                config[param]["value"] = trial.suggest_float(
                    param, extras.get("min"), extras.get("max"), log=log
                )
            elif type(extras.get("min")) == int:
                log = "log" in param
                config[param]["value"] = trial.suggest_int(
                    param, extras.get("min"), extras.get("max"), log=log
                )
            else:
                print(f"{LOG_PREFIX} Unknown parameter type, help! {param=}, {extras=}")
        return config, trial

    def _make_trial_from_objective(self, objective_func):
        print("attempting to make trial params from objective func")
        study_copy = self.study.copy()
        try:
            study_copy.optimize(objective_func, n_trials=1, timeout=2)
        except TimeoutError:
            raise Exception(
                "Passed optuna objective functions cannot actually train. Must execute in 2 seconds. See docs."
            )

        return study_copy.last_trial.params, study_copy.last_trial

    def _make_optuna_pruner(self, pruner_args: Dict, epochs: Optional[int]):
        type_ = pruner_args.get("type")
        if not type_:
            wandb.termwarn("No pruner selected, using Optuna default median pruner")
            return None
        elif type_ == "HyperbandPruner":
            return optuna.pruners.HyperbandPruner(
                min_resource=pruner_args.get("min_resource", 1),
                max_resource=epochs or 100,
                reduction_factor=pruner_args.get("reduction_factor", 3),
            )
        else:
            wandb.termwarn(f"Pruner: {type_} not yet supported.")
