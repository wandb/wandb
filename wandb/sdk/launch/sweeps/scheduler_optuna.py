import base64
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from importlib.machinery import SourceFileLoader
from pprint import pformat
from types import ModuleType
from typing import Any, Dict, List, Optional, Tuple

import click
import optuna

import wandb
from wandb.apis.public import Artifact, QueuedRun, Run
from wandb.sdk.launch.sweeps import SchedulerError
from wandb.sdk.launch.sweeps.scheduler import RunState, Scheduler, SweepRun

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
class OptunaRun:
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
        *args: Optional[Any],
        **kwargs: Optional[Any],
    ):
        super().__init__(*args, **kwargs)

        # Optuna
        self._study: Optional[optuna.study.Study] = None
        self._storage_path: Optional[str] = None
        self._trial_func = self._make_trial
        self._optuna_runs: Dict[str, OptunaRun] = {}

    @property
    def study(self) -> optuna.study.Study:
        if not self._study:
            raise SchedulerError("Optuna study=None before scheduler.start")
        return self._study

    @property
    def study_name(self):
        if not self._study:
            return f"optuna-study-{self._sweep_id}"
        return self.study.study_name

    @property
    def study_string(self) -> str:
        msg = f"{LOG_PREFIX}{'Loading' if self._wandb_run.resumed else 'Creating'}"
        msg += f" optuna study: {self.study_name} [storage:{self.study._storage.__class__.__name__}"
        msg += f", direction:{self.study.direction.name.capitalize()}"
        msg += f", pruner:{self.study.pruner.__class__.__name__}"
        msg += f", sampler:{self.study.sampler.__class__.__name__}]"
        return msg

    @property
    def formatted_trials(self) -> str:
        """
        Prints out trials from the current optuna study in a pleasing
        format, showing the total/best/last metrics

        returns a string with whitespace
        """
        trials = {}
        for trial in self.study.trials:
            i = trial.number + 1
            i_str = f"trial-{'0' * max(0, 2 - int(i / 10))}{i}"
            vals = list(trial.intermediate_values.values())
            if len(vals) > 0:
                best = (
                    max(vals)
                    if self.study.direction == optuna.study.StudyDirection.MAXIMIZE
                    else min(vals)
                )
                trials[
                    f"trial-{i_str}"
                ] = f"state: {trial.state.name}, metrics: {len(vals)}, best: {round(best, 5)}, last: {round(vals[-1], 5)}"
            else:
                trials[f"trial-{i_str}"] = "total: 0, best: None, last: None"
        return pformat(trials)

    def _validate_optuna_study(self, study: optuna.Study) -> Optional[str]:
        """
        Accepts an optuna study, runs validation
        Returns an error string if validation fails
        """
        if len(study.trials) > 0:
            wandb.termlog(f"{LOG_PREFIX}User provided study has prior trials")

        if study.user_attrs:
            wandb.termwarn(
                f"{LOG_PREFIX}user_attrs are ignored from provided study ({study.user_attrs})"
            )

        if study._storage is not None:
            wandb.termlog(
                f"{LOG_PREFIX}User provided study has storage:{study._storage}"
            )

        # TODO(gst): implement *requirements*
        return None

    def _load_optuna_from_user_provided_artifact(
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

        # load user-set optuna class definition file
        artifact = self._wandb_run.use_artifact(artifact_name, type="optuna")
        if not artifact:
            raise SchedulerError(
                f"{LOG_PREFIX}Failed to load artifact: {artifact_name}"
            )

        path = artifact.download()
        mod, err = _get_module("optuna", f"{path}/{OptunaComponents.main_file.value}")
        if not mod:
            raise SchedulerError(
                f"{LOG_PREFIX}Failed to load optuna from path {path}/{OptunaComponents.main_file.value} "
                f" in artifact: {artifact_name} with error: {err}"
            )

        # Set custom optuna trial creation method
        try:
            self._objective_func = mod.objective
            self._trial_func = self._make_trial_from_objective
        except AttributeError:
            pass

        try:
            study = mod.study()
            val_error: Optional[str] = self._validate_optuna_study(study)
            wandb.termlog(
                f"{LOG_PREFIX}User provided study, ignoring pruner and sampler"
            )
            if val_error:
                raise SchedulerError(err)
            return study, None, None
        except AttributeError:
            pass

        pruner, sampler = None, None
        try:
            pruner = mod.pruner()
        except AttributeError:
            pass

        try:
            sampler = mod.sampler()
        except AttributeError:
            pass

        return None, pruner, sampler

    def _get_and_download_artifact(self, component: OptunaComponents) -> Optional[str]:
        """
        Finds and downloads an artifact, returns name of downloaded artifact
        """
        try:
            artifact_name = f"{self._entity}/{self._project}/{component.name}:latest"
            component_artifact: Artifact = self._wandb_run.use_artifact(artifact_name)
            path = component_artifact.download()

            storage_files = os.listdir(path)
            if component.value in storage_files:
                if path.startswith("./"):  # TODO(gst): robust way of handling this
                    path = path[2:]
                wandb.termlog(
                    f"{LOG_PREFIX}Loaded storage from artifact: {artifact_name}"
                )
                return f"{path}/{component.value}"
        except wandb.errors.CommError as e:
            raise SchedulerError(str(e))
        except Exception as e:
            raise SchedulerError(str(e))

        return None

    def _load_optuna(self) -> None:
        """
        If our run was resumed, attempt to restore optuna artifacts from run state

        Create an optuna study with a sqlite backened for loose state management
        """
        study, pruner, sampler = None, None, None
        optuna_artifact_name = self._sweep_config.get("optuna", {}).get("artifact")
        if optuna_artifact_name:
            study, pruner, sampler = self._load_optuna_from_user_provided_artifact(
                optuna_artifact_name
            )

        existing_storage = None
        if self._wandb_run.resumed or self._kwargs.get("resumed"):
            existing_storage = self._get_and_download_artifact(OptunaComponents.storage)

        if study:  # user provided a valid study in downloaded artifact
            if existing_storage:
                wandb.termwarn("Resuming state w/ user-provided study is unsupported")
            self._study = study
            wandb.termlog(self.study_string)
            return
        # making a new study

        if pruner:
            wandb.termlog(f"{LOG_PREFIX}Loaded pruner ({pruner.__class__.__name__})")
        else:
            pruner_args = self._sweep_config.get("optuna", {}).get("pruner", {})
            if pruner_args:
                pruner = load_optuna_pruner(
                    pruner_args["type"], pruner_args.get("args")
                )
                wandb.termlog(f"{LOG_PREFIX}Loaded pruner ({pruner})")
            else:
                wandb.termlog(f"{LOG_PREFIX}No pruner args, defaulting to MedianPruner")

        if sampler:
            wandb.termlog(f"{LOG_PREFIX}Loaded sampler ({sampler.__class__.__name__})")
        else:
            sampler_args = self._sweep_config.get("optuna", {}).get("sampler", {})
            if sampler_args:
                sampler = load_optuna_sampler(
                    sampler_args["type"], sampler_args.get("args")
                )
                wandb.termlog(f"{LOG_PREFIX}Loaded sampler ({sampler})")
            else:
                wandb.termlog(f"{LOG_PREFIX}No sampler args, defaulting to TPESampler")

        direction = self._sweep_config.get("metric", {}).get("goal")
        self._storage_path = existing_storage or OptunaComponents.storage.value
        # TODO(gst): implement basic early_stopping opt
        self._study = optuna.create_study(
            study_name=self.study_name,
            storage=f"sqlite:///{self._storage_path}",
            pruner=pruner,
            sampler=sampler,
            load_if_exists=True,
            direction=direction,
        )
        wandb.termlog(self.study_string)

        if existing_storage:
            wandb.termlog(
                f"{LOG_PREFIX}Loaded prior runs ({len(self.study.trials)}) from "
                f"storage ({existing_storage})\n {self.formatted_trials}"
            )

        return

    def _load_state(self) -> None:
        """
        Called when Scheduler class invokes start()
        Load optuna study sqlite data from an artifact in controller run
        """
        self._load_optuna()

    def _save_state(self) -> None:
        """
        Called when Scheduler class invokes exit()

        Save optuna study sqlite data to an artifact in the controller run
        """
        artifact = wandb.Artifact(OptunaComponents.storage.name, type="optuna")
        if not self._storage_path:
            wandb.termwarn(
                f"{LOG_PREFIX}No db storage path found, saving to default path"
            )
            self._storage_path = OptunaComponents.storage.value

        artifact.add_file(self._storage_path)
        self._wandb_run.log_artifact(artifact)

        wandb.termlog(f"{LOG_PREFIX}Saved study with trials:\n{self.formatted_trials}")
        return

    def _get_next_sweep_run(self, worker_id: int) -> Optional[SweepRun]:
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
        self._optuna_runs[srun.id] = OptunaRun(
            num_metrics=0,
            trial=trial,
            sweep_run=srun,
        )
        return srun

    def _get_run_history(self, run_id: str) -> List[int]:
        """
        Gets logged metric history for a given run_id
        """
        if run_id in self._runs:
            queued_run: Optional[QueuedRun] = self._runs[run_id].queued_run
            if not queued_run or queued_run.state == "pending":
                return []

        try:
            api_run: Run = self._public_api.run(
                f"{queued_run.entity}/{queued_run.project}/{run_id}"
            )
        except Exception as e:
            logger.debug(f"Failed to poll run from public api: {str(e)}")
            return []

        metric_name = self._sweep_config["metric"]["name"]
        history = api_run.scan_history(keys=["_step", metric_name])
        metrics = [x[metric_name] for x in history]

        return metrics

    def _poll_run(self, orun: OptunaRun) -> bool:
        """
        Polls metrics for a run, returns true if finished
        """
        metrics = self._get_run_history(orun.sweep_run.id)
        for i, metric in enumerate(metrics[orun.num_metrics :]):
            logger.debug(f"{orun.sweep_run.id} (step:{i+orun.num_metrics}) {metrics}")
            prev = orun.trial._cached_frozen_trial.intermediate_values
            if orun.num_metrics + i not in prev:
                orun.trial.report(metric, orun.num_metrics + i)

            if orun.trial.should_prune():
                wandb.termlog(f"{LOG_PREFIX}Optuna pruning run: {orun.sweep_run.id}")
                self.study.tell(orun.trial, state=optuna.trial.TrialState.PRUNED)
                self._stop_run(orun.sweep_run.id)
                return True

        orun.num_metrics = len(metrics)

        # run hasn't started
        if self._runs[orun.sweep_run.id].state == RunState.ALIVE or len(metrics) == 0:
            logger.debug(f"Run ({orun.sweep_run.id}) has no metrics")
            return False

        # run is complete
        prev_metrics = orun.trial._cached_frozen_trial.intermediate_values
        last_value = prev_metrics[orun.num_metrics - 1]
        self.study.tell(
            trial=orun.trial,
            state=optuna.trial.TrialState.COMPLETE,
            values=last_value,
        )
        wandb.termlog(
            f"{LOG_PREFIX}Completing trial for run ({orun.sweep_run.id}) "
            f"[last metric: {last_value}, total: {orun.num_metrics}]"
        )

        # Delete run in Scheduler memory, freeing up worker
        del self._runs[orun.sweep_run.id]

        return True

    def _poll_running_runs(self) -> None:
        """
        Iterates through runs, getting metrics, reporting to optuna

        Returns list of runs optuna marked as PRUNED, to be deleted
        """
        wandb.termlog(f"{LOG_PREFIX}Polling. Current state:\n{self.formatted_trials}")
        to_kill = []
        for run_id, orun in self._optuna_runs.items():
            run_finished = self._poll_run(orun)
            if run_finished:
                wandb.termlog(f"{LOG_PREFIX}Run: {run_id} finished.")
                logger.debug(f"Finished run, study state: {self.study.trials}")
                to_kill += [run_id]

        for r in to_kill:
            del self._optuna_runs[r]

    def _make_trial(self) -> Tuple[Dict[str, Any], optuna.Trial]:
        """
        Use a wandb.config to create an optuna trial object with correct
            optuna distributions
        """
        trial = self.study.ask()
        config: Dict[str, Dict[str, Any]] = defaultdict(dict)
        for param, extras in self._sweep_config["parameters"].items():
            if extras.get("values"):
                config[param]["value"] = trial.suggest_categorical(
                    param, extras["values"]
                )
            elif extras.get("value"):
                config[param]["value"] = trial.suggest_categorical(
                    param, [extras["value"]]
                )
            elif type(extras.get("min")) == float:
                if not extras.get("max"):
                    raise SchedulerError(
                        f"{LOG_PREFIX}Error converting config. 'min' requires 'max'"
                    )
                log = "log" in param
                config[param]["value"] = trial.suggest_float(
                    param, extras["min"], extras["max"], log=log
                )
            elif type(extras.get("min")) == int:
                if not extras.get("max"):
                    raise SchedulerError(
                        f"{LOG_PREFIX}Error converting config. 'min' requires 'max'"
                    )
                log = "log" in param
                config[param]["value"] = trial.suggest_int(
                    param, extras["min"], extras["max"], log=log
                )
            else:
                logger.debug(f"Unknown parameter type: {param=}, {extras=}")
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
        wandb.termlog(
            f"{LOG_PREFIX}Making trial params from objective func, ignoring sweep config parameters"
        )
        study_copy = optuna.create_study()
        study_copy.add_trials(self.study.trials)

        # Signal handler to raise error if objective func takes too long
        import signal

        def handler(signum, frame):
            raise TimeoutError(
                "Passed optuna objective function only creates parameter config."
                f" Do not train; must execute in {2} seconds. See docs."
            )

        signal.signal(signal.SIGALRM, handler)
        signal.alarm(2)

        study_copy.optimize(self._objective_func, n_trials=1)

        temp_trial = study_copy.trials[-1]
        # convert from optuna-type param config to wandb-type param config
        config: Dict[str, Dict[str, Any]] = defaultdict(dict)
        for param, value in temp_trial.params.items():
            config[param]["value"] = value

        new_trial = self.study.ask(fixed_distributions=temp_trial.distributions)

        return config, new_trial

    def _poll(self) -> None:
        self._poll_running_runs()

    def _exit(self) -> None:
        pass

    def _cleanup_runs(self, runs_to_remove) -> None:
        logger.debug(f"[_cleanup_runs] not removing: {runs_to_remove}")


def validate_optuna_pruner(args: Dict[str, Any]) -> bool:
    if not args.get("type"):
        wandb.termerror("key: 'type' is required")
        return False

    try:
        _ = load_optuna_pruner(args["type"], args.get("args"))
    except Exception as e:
        wandb.termerror(f"Error loading optuna pruner: {e}")
        return False
    return True


def validate_optuna_sampler(args: Dict[str, Any]) -> bool:
    if not args.get("type"):
        wandb.termerror("key: 'type' is required")
        return False

    try:
        _ = load_optuna_sampler(args["type"], args.get("args"))
    except Exception as e:
        wandb.termerror(f"Error loading optuna sampler: {e}")
        return False
    return True


def load_optuna_pruner(
    type_: str,
    args: Optional[Dict[str, Any]],
) -> optuna.pruners.BasePruner:
    args = args or {}
    if type_ == "NopPruner":
        return optuna.pruners.NopPruner(**args)
    elif type_ == "MedianPruner":
        return optuna.pruners.MedianPruner(**args)
    elif type_ == "HyperbandPruner":
        return optuna.pruners.HyperbandPruner(**args)
    elif type_ == "PatientPruner":
        wandb.termerror(
            "PatientPruner requires passing in a wrapped_pruner, which is not "
            "supported through this simple config path. Please use the adv. "
            "artifact upload path for this pruner, specified in the docs."
        )
        return optuna.pruners.PatientPruner(**args)
    elif type_ == "PercentilePruner":
        return optuna.pruners.PercentilePruner(**args)
    elif type_ == "SuccessiveHalvingPruner":
        return optuna.pruners.SuccessiveHalvingPruner(**args)
    elif type_ == "ThresholdPruner":
        return optuna.pruners.ThresholdPruner(**args)

    raise Exception(f"Optuna pruner type: {type_} not supported")


def load_optuna_sampler(
    type_: str,
    args: Optional[Dict[str, Any]],
) -> optuna.samplers.BaseSampler:
    args = args or {}
    if type_ == "BruteForceSampler":
        return optuna.samplers.BruteForceSampler(**args)
    elif type_ == "CmaEsSampler":
        return optuna.samplers.CmaEsSampler(**args)
    elif type_ == "GridSampler":
        return optuna.samplers.GridSampler(**args)
    elif type_ == "IntersectionSearchSpace":
        return optuna.samplers.IntersectionSearchSpace(**args)
    elif type_ == "MOTPESampler":
        return optuna.samplers.MOTPESampler(**args)
    elif type_ == "NSGAIISampler":
        return optuna.samplers.NSGAIISampler(**args)
    elif type_ == "PartialFixedSampler":
        wandb.termerror(
            "PartialFixedSampler requires passing in a base_sampler, which is not "
            "supported through this simple config path. Please use the adv. "
            "artifact upload path for this sampler, specified in the docs."
        )
        return optuna.samplers.PartialFixedSampler(**args)
    elif type_ == "RandomSampler":
        return optuna.samplers.RandomSampler(**args)
    elif type_ == "TPESampler":
        return optuna.samplers.TPESampler(**args)
    elif type_ == "QMCSampler":
        return optuna.samplers.QMCSampler(**args)

    raise Exception(f"Optuna sampler type: {type_} not supported")
