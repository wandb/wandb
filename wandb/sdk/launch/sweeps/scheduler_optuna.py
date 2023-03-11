import base64
from collections import defaultdict
from enum import Enum
import logging
import queue
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from types import ModuleType
from importlib.machinery import SourceFileLoader
import click
import optuna
from optuna.pruners import HyperbandPruner, SuccessiveHalvingPruner

import wandb
from wandb.sdk.launch.sweeps import SchedulerError
from wandb.sdk.launch.sweeps.scheduler import (
    _Worker,
    RunState,
    Scheduler,
    SweepRun,
)
from wandb.wandb_agent import _create_sweep_command_args

from wandb.apis.public import Artifact, QueuedRun
from wandb.sdk.wandb_run import Run as SdkRun
from wandb.apis.public import Run

logger = logging.getLogger(__name__)
optuna.logging.set_verbosity(optuna.logging.WARNING)


LOG_PREFIX = f"{click.style('optuna sched:', fg='bright_blue')} "


class OptunaComponents(Enum):
    main_file = "optuna_wandb.py"
    storage = "optuna.db"
    study = "optuna-study"
    pruner = "optuna-pruner"
    sampler = "optuna-sampler"


@dataclass
class _OptunaRun:
    num_metrics: int
    trial: optuna.Trial
    sweep_run: SweepRun


def _encode(run_id: str) -> str:
    """
    Helper to hash the run id for backend format
    """
    return base64.b64decode(bytes(run_id.encode("utf-8"))).decode("utf-8").split(":")[2]


def _get_module(
    module_name: str, filepath: str
) -> Tuple[Optional[ModuleType], Optional[str]]:
    """
    Helper function that loads a python module from provided filepath
    """
    try:
        loader = SourceFileLoader(module_name, filepath)
        mod = ModuleType(loader.name)
        loader.exec_module(mod)
    except Exception as e:
        return None, str(e)

    return mod, None


class OptunaScheduler(Scheduler):
    def __init__(
        self,
        *args: Any,
        num_workers: int = 2,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self._workers: Dict[int, _Worker] = {}
        self._num_workers: num_workers
        self._job_queue: "queue.Queue[SweepRun]" = queue.Queue()

        # Scheduler controller run
        self._wandb_run: SdkRun = self._init_wandb_run()

        # Optuna
        self.study: optuna.study.Study = None
        self._trial_func = self._make_trial
        self._optuna_runs: Dict[str, _OptunaRun] = {}

    def _init_wandb_run(self) -> SdkRun:
        """
        Controls resume or init logic for a scheduler wandb run
        """
        if self._kwargs.get("run_id"):  # resume
            return wandb.init(run_id=self._kwargs["run_id"], resume="must")

        return wandb.init(name=f"optuna-scheduler-{self._sweep_id}")

    def _validate_optuna_study(self, study: optuna.Study) -> Optional[str]:
        """
        Accepts an optuna study, runs validation
        Returns an error string if validation fails
        """
        if study.trials > 0:
            wandb.termlog(f"{LOG_PREFIX}User provided study has prior trials")

        if study.user_attrs:
            wandb.termwarn(
                f"{LOG_PREFIX}Provided user_attrs are ignored from provided study ({study.user_attrs})"
            )

        if study._storage is not None:
            wandb.termlog(
                f"{LOG_PREFIX}User provided study has storage:{study._storage}"
            )

        # TODO(gst): implement *requirements*
        return None

    def _load_optuna_from_artifact(
        self,
        artifact_name: str,
    ) -> Tuple[
        Optional[optuna.Study],
        Optional[optuna.pruners.BasePruner],
        Optional[optuna.samplers.BaseSampler],
    ]:
        """
        Loads custom optuna classes from user-supplied artifact

        Returns:
            study: a custom optuna study object created by the user
            pruner: a custom optuna pruner supplied by user
            sampler: a custom optuna sampler supplied by user
        """
        wandb.termlog(f"{LOG_PREFIX}User set optuna.artifact, attempting download.")
        artifact = self._wandb_run.use_artifact(artifact_name, type="optuna")
        if not artifact:
            raise SchedulerError(
                f"{LOG_PREFIX}Failed to load artifact: {artifact_name}"
            )

        path = artifact.download()
        mod, err = _get_module("optuna", f"{path}/{OptunaComponents.main_file}")
        if not mod:
            raise SchedulerError(
                f"{LOG_PREFIX}Failed to load optuna from artifact: "
                f"{artifact_name} with error: {err}"
            )

        # Set custom optuna trial creation method
        if mod.objective:
            self._trial_func = self._make_trial_from_objective
            self._objective_func = mod.objective

        if mod.study:
            wandb.termlog(
                f"{LOG_PREFIX}User provided study, ignoring pruner and sampler"
            )
            val_error: Optional[str] = self._validate_optuna_study(mod.study())
            if val_error:
                raise SchedulerError(err)
            return mod.study(), None, None

        pruner = mod.pruner() if mod.pruner else None
        sampler = mod.sampler() if mod.sampler else None
        return None, pruner, sampler

    def _get_and_download_artifact(self, component_name: str) -> Optional[Artifact]:
        """
        Finds and downloads an artifact, returns name of downloaded artifact
        """
        # TODO(gst): type these so they can be actually used in load_study
        try:
            component_artifact = (
                f"{self._entity}/{self._project}{self._wandb_run.id}/{component_name}"
            )
            component: Artifact = self._wandb_run.use_artifact(component_artifact)
            component.download()
        # TODO(gst): catch not found and return None
        # except NotFound:
        except Exception as e:
            raise SchedulerError(str(e))

        return component

    def _load_optuna_from_wandb_run(self) -> Tuple[Optional[optuna.Study]]:
        # our scheduler was resumed, try to load state
        study = self._get_and_download_artifact(OptunaComponents.study)
        if study:  # done
            return study

        # TODO(gst): when could this ever happen????? maybe we just want to save storage

        # recreate study from saved individual components
        storage = self._get_and_download_artifact(OptunaComponents.storage)
        pruner = self._get_and_download_artifact(OptunaComponents.pruner)
        sampler = self._get_and_download_artifact(OptunaComponents.sampler)

        return optuna.load_study(
            study_name=f"optuna-study-{self._sweep_id}",
            storage=f"sqlite:///{storage.name}",
            pruner=pruner,
            sampler=sampler,
        )

    def _load_optuna(self) -> None:
        """
        If our run was resumed, attempt to resture optuna artifacts from run state

        Create an optuna study with a sqlite backened for loose state management
        """
        optuna_artifact_name = self._sweep_config.get("optuna", {}).get("artifact")
        if optuna_artifact_name:
            study, pruner, sampler = self._load_optuna_from_artifact(
                optuna_artifact_name
            )
        elif self._wandb_run.resumed:
            study, pruner, sampler = self._load_optuna_from_wandb_run()

        if study:  # study supercedes pruner and sampler
            self.study = study
            return

        # making a new study

        pruner_args = self._sweep_config.get("optuna", {}).get("pruner", {})
        if pruner and pruner_args and optuna_artifact_name:
            wandb.termwarn(
                f"{LOG_PREFIX}Loaded pruner from given artifact, `pruner_args` are ignored"
            )
        elif pruner_args:
            pruner = self._make_optuna_pruner(pruner_args)
        else:
            wandb.termlog(f"{LOG_PREFIX}No pruner args, using Optuna defaults")

        sampler_args = self._sweep_config.get("optuna", {}).get("sampler", {})
        if sampler and sampler_args and optuna_artifact_name:
            wandb.termwarn(
                f"{LOG_PREFIX}Loaded sampler from given artifact, `sampler_args` are ignored"
            )
        elif sampler_args:
            sampler = self._make_optuna_sampler(sampler_args)
        else:
            wandb.termlog(f"{LOG_PREFIX}No sampler args, using Optuna defaults")

        study_name = f"optuna-study-{self._sweep_id}"
        storage_name = f"sqlite:///{study_name}.db"
        direction = self._sweep_config.get("metric", {}).get("goal")

        _create_msg = (
            f"{LOG_PREFIX}Creating optuna study: {study_name} [storage:{storage_name}"
        )
        if direction:
            _create_msg += f", direction:{direction}"
        if pruner:
            _create_msg += f", pruner:{pruner.__class__}"
        if sampler:
            _create_msg += f", sampler:{sampler.__class__}"

        wandb.termlog(f"{_create_msg}]")
        self.study = optuna.create_study(
            study_name=study_name,
            storage=storage_name,
            pruner=pruner,
            sampler=sampler,
            # load_if_exists=True,  # TODO(gst): verify this is correct functionality
            direction=direction,
        )

    def _load_scheduler_state(self) -> None:
        """
        Load optuna study sqlite data from an artifact in controller run
        """
        raise NotImplementedError

    def _save_scheduler_state(self) -> None:
        """
        Save optuna study sqlite data to an artifact in the controller run

        TODO(gst): extend this to the other objects? study? pruner? sampler?
        """
        artifact_name = f"{self._entity}/{self._project}{self._wandb_run.id}/{OptunaComponents.storage}"
        scheduler_artifact = wandb.Artifact(artifact_name, type="scheduler")
        scheduler_artifact.add_file(f".{self.study._storage}")
        self._wandb_run.log_artifact(scheduler_artifact)
        wandb.termlog(
            f"{LOG_PREFIX}Saved scheduler state to run: {self._wandb_run.id} "
            f"in artifact: {scheduler_artifact.name}"
        )

        # TODO(gst): consider wandb.save() and wandb.restore() for state storage

    def _start(self) -> None:
        """
        Load optuna state, then register workers as agents
        """
        self._load_optuna()
        for worker_id in range(self._num_workers):
            wandb.termlog(f"{LOG_PREFIX}Starting AgentHeartbeat worker {worker_id}\n")
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
        """
        Query job queue for available jobs if we have space in our worker cap
        """
        if not self.is_alive():
            return

        if self._job_queue.empty() and len(self._runs) < self._num_workers:
            config, trial = self._trial_func()
            run: dict = self._api.upsert_run(
                project=self._project,
                entity=self._entity,
                sweep_name=self._sweep_id,
                config=config,
            )[0]
            srun = SweepRun(
                id=_encode(run["id"]),
                args=config,
                worker_id=worker_id,
            )
            # internal scheduler handling needs this
            self._runs[srun.id] = srun
            self._job_queue.put(srun)
            # track the trial and metrics for optuna
            self._optuna_runs[srun.id] = _OptunaRun(
                num_metrics=0,
                trial=trial,
                sweep_run=srun,
            )

    def _run(self) -> None:
        """
        Poll currently known runs for new metrics
        report new metrics to optuna
        send kill signals to existing runs if pruned
        hearbeat workers with backend
        create new runs if necessary from optuna suggestions
        launch new runs
        """
        # go through every run we know is alive and get metrics
        to_kill = self._poll_running_runs()
        for run_id in to_kill:
            del self._optuna_runs[run_id]
            self._stop_run(run_id)

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
            RunState.DEAD,
            RunState.UNKNOWN,
        ]:
            return

        # send to launch
        command = _create_sweep_command_args({"args": srun.args})["args_dict"]
        self._add_to_launch_queue(
            run_id=srun.id,
            config={"overrides": {"run_config": command}},
        )

    def _get_run_history(self, run_id: str) -> Tuple[List[int], bool]:
        """
        Gets logged metric history for a given run_id
        """
        if run_id in self._runs:
            queued_run: Optional[QueuedRun] = self._runs[run_id].queued_run
            if not queued_run or queued_run.state == "pending":
                return [], False

            # TODO(gst): just noop here
            queued_run.wait_until_running()

        try:
            api_run: Run = self._public_api.run(self._runs[run_id].full_name)
        except Exception as e:
            logger.debug(f"Failed to poll run from public api with error: {str(e)}")
            return [], True

        metric_name = self._sweep_config["metric"]["name"]
        history = api_run.scan_history(keys=["_step", metric_name])
        metrics = [x[metric_name] for x in history]

        return metrics, api_run.state == "finished"

    def _poll_run(self, orun: _OptunaRun) -> bool:
        """
        Polls metrics for a run, returns true if finished
        """
        metrics, run_finished = self._get_run_history(orun.sweep_run.id)
        for i, metric in enumerate(metrics[orun.num_metrics :]):
            logger.debug(f"{orun.sweep_run.id} (step:{i+orun.num_metrics}) {metrics}")
            orun.trial.report(metric, orun.num_metrics + i)
            orun.num_metrics = len(metrics)

            if orun.trial.should_prune():
                wandb.termlog(f"{LOG_PREFIX}Optuna pruning run: {orun.sweep_run.id}")
                self.study.tell(orun.trial, state=optuna.trial.TrialState.PRUNED)
                return True
        return run_finished

    def _poll_running_runs(self) -> List[str]:
        """
        Iterates through runs, getting metrics, reporting to optuna

        Returns list of runs optuna marked as PRUNED, to be deleted
        """
        # TODO(gst): make threadsafe?
        wandb.termlog(f"{LOG_PREFIX}Polling runs for metrics.")
        to_kill = []
        for run_id, orun in self._optuna_runs.items():
            run_finished = self._poll_run(orun)

            if run_finished:  # Does this ever happen?
                self.study.tell(orun.trial, state=optuna.trial.TrialState.COMPLETE)
                wandb.termlog(f"{LOG_PREFIX}Run: {run_id} finished.")
                logger.debug(f"Finished run, study state: {self.study.trials}")
                to_kill += [run_id]
        return to_kill

    def _make_trial(self) -> Tuple[Dict[str, Any], optuna.Trial]:
        """
        Use a wandb.config to create an optuna trial object with correct
            optuna distributions
        """
        trial = self.study.ask()
        config: Dict[str, Dict[str, Any]] = defaultdict(dict)
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
                logger.debug(f"Unknown parameter type! {param=}, {extras=}")
        return config, trial

    def _make_trial_from_objective(self) -> Tuple[Dict[str, Any], optuna.Trial]:
        """
        This is the core logic that turns a user-provided MOCK objective func
            into wandb params, allowing for pythonic search spaces.
            MOCK: does not actually train, only configures params

        First creates a copy of our real study, quarantined from fake metrics

        Then calls optuna optimize on the copy study, passing in the
        loaded-from-user objective function with an aggresive timeout:
            ensures the model does not actually train.

        Retrieves created mock-trial from study copy and formats params for wandb

        Finally, ask our real study for a trial with fixed params = retrieved

        Returns wandb formatted config and optuna trial from real study
        """
        wandb.termlog(f"{LOG_PREFIX}Making trial params from objective func")
        study_copy = optuna.create_study()
        study_copy.add_trials(self.study.trials)
        try:
            # TODO(gst): this the right timeout val?
            study_copy.optimize(self._objective_func, n_trials=1, timeout=2)
        except TimeoutError:
            raise SchedulerError(
                "Passed optuna objective functions cannot actually train."
                " Must execute in 2 seconds. See docs."
            )

        temp_trial = study_copy.trials[-1]
        # convert from optuna-type param config to wandb-type param config
        config: Dict[str, Dict[str, Any]] = defaultdict(dict)
        for param, value in temp_trial.params.items():
            config[param]["value"] = value

        new_trial = self.study.ask(fixed_distributions=temp_trial.distributions)

        return config, new_trial

    def _make_optuna_pruner(
        self, pruner_args: Dict[str, Any], epochs: Optional[int] = 100
    ) -> Union[HyperbandPruner, SuccessiveHalvingPruner]:
        """
        Uses sweep config values in the optuna dict to configure pruner.
        Example sweep_config.yaml:

        ```
        method: optuna
        optuna:
           pruner:
              type: SuccessiveHalvingPruner
              min_resource: 10
              reduction_factor: 3
        ```
        """
        type_ = pruner_args.get("type")
        if type_ == "HyperbandPruner":
            wandb.termlog(f"{LOG_PREFIX}Using the optuna HyperbandPruner")
            return HyperbandPruner(
                min_resource=pruner_args.get("min_resource", 1),
                max_resource=epochs,
                reduction_factor=pruner_args.get("reduction_factor", 3),
            )
        elif type_ == "SuccessiveHalvingPruner":
            wandb.termlog(f"{LOG_PREFIX}Using the optuna SuccessiveHalvingPruner")
            return SuccessiveHalvingPruner(
                min_resource=pruner_args.get("min_resource", 1),
                reduction_factor=pruner_args.get("reduction_factor", 3),
            )

        raise SchedulerError(f"Pruner: {type_} not yet supported.")

    def _make_optuna_sampler(
        self, sampler_args: Dict[str, Any]
    ) -> optuna.samplers.BaseSampler:
        type_ = sampler_args.get("type")

        if type_ == "RandomSampler":
            return optuna.samplers.RandomSampler(seed=sampler_args.get("seed"))

        raise SchedulerError(f"Pruner: {type_} not yet supported.")

    def _exit(self) -> None:
        pass
