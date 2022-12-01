from typing import Any, Dict, List
import wandb
from dataclasses import dataclass

from collections import defaultdict

import time
import socket
import optuna
from optuna.distributions import (
    CategoricalDistribution,
    IntDistribution,
    FloatDistribution,
)
import queue
import base64

from wandb.sdk.launch.sweeps import SchedulerError

from wandb.sdk.launch.sweeps.scheduler_sweep import _Worker
from wandb.sdk.launch.sweeps.scheduler import (
    LOG_PREFIX,
    Scheduler,
    SchedulerState,
    SimpleRunState,
    SweepRun,
)
from wandb.sdk.wandb_run import Run
from wandb.wandb_agent import Agent as LegacySweepAgent

from wandb.apis.public import Api
from wandb.sdk.internal.internal_api import Api as InternalApi


@dataclass
class RunTrial:
    id: str  # mirrors run id
    trial: Any
    cur_epoch: int = 0


def validate_optuna_config(config: Dict[str, Any]):
    for key in config:
        if key == "method":
            if config[key] in ["OPTUNA.METHOD", "optuna", "bayes"]:
                pass
            else:
                raise Exception(f"Method: '{config[key]}' is not optuna!")
        elif key == "metric":
            metric = config[key]
            if metric.get("goal") == "maximize":
                raise Exception("Can't maximize with optuna, only minimize")
        elif params := config[key] == "parameters":
            for p in params:
                if p == "pruner":
                    pass


class OptunaScheduler(Scheduler):
    """
    Uses optuna instead of anaconda2 to determine parameters
    """

    def __init__(
        self,
        *args: Any,
        num_workers: int = 1,  # set to 1 for now
        heartbeat_queue_timeout: float = 1.0,
        heartbeat_queue_sleep: float = 1.0,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        # Optionally run multiple workers in (pseudo-)parallel. Workers do not
        # actually run training workloads, they simply send heartbeat messages
        # (emulating a real agent) and add new runs to the launch queue. The
        # launch agent is the one that actually runs the training workloads.
        self._workers: Dict[int, _Worker] = {}
        self._num_workers: int = num_workers
        # Thread will pop items off the Sweeps RunQueue using AgentHeartbeat
        # and put them in this internal queue, which will be used to populate
        # the Launch RunQueue
        self._heartbeat_queue: "queue.Queue[SweepRun]" = queue.Queue()
        self._heartbeat_queue_timeout: float = heartbeat_queue_timeout
        self._heartbeat_queue_sleep: float = heartbeat_queue_sleep

        self.study: optuna.study.Study = self._load_db()

        self._run_history = []
        self._optuna_config = self._make_optuna_config()

        self._public_api = Api()
        self._internal_api = InternalApi()

    def _exit(self) -> None:
        pass

    def _make_optuna_config(self) -> Dict[str, Any]:
        """
        !! This is where we ensure the user provided config is actually
        compatible with optuna, which is non trivial. This will have to be updated
        with new versions, etc.
        """

        validate_optuna_config(self._sweep_config)

        distributions = {}
        for param, extras in self._sweep_config["parameters"].items():
            print(param, extras)
            if values := extras.get("values"):  # categorical
                distributions[param] = CategoricalDistribution(values)
            elif value := extras.get("value"):
                distributions[param] = CategoricalDistribution([value])
            elif type(extras.get("min")) == float:
                log = "log" in param
                distributions[param] = FloatDistribution(
                    extras.get("min"), extras.get("max"), log=log
                )
            elif type(extras.get("min")) == int:
                log = "log" in param
                distributions[param] = IntDistribution(
                    extras.get("min"), extras.get("max"), log=log
                )
            else:
                print(f"{LOG_PREFIX} Unknown parameter type, help! {param=}, {extras=}")

        # Do we want to set the metric here? Note for the users, we access the metric
        # when pruning, so we need to know what its called. defaults to "loss"
        # epochs defaults to epoch, could also name step...

        return distributions

    def _load_db(self, sweep_name: str = "example-study"):
        """
        Create an optuna study with a sqlite backened for loose state management
        """
        # TODO(gst): add to validate function to confirm this exists, warn user
        params = self._sweep_config.get("parameters", {})
        epochs = params.get("epochs", {}).get("value") or 20  # could also use STEP here
        pruner_args = params.get("pruner", {})

        pruner = optuna.pruners.HyperbandPruner(
            min_resource=pruner_args.get(
                "min_resource", 1
            ),  # TODO(gst): defaults are from tutorial
            max_resource=epochs,
            reduction_factor=pruner_args.get("reduction_factor", 3),
        )

        storage_name = f"sqlite:///{sweep_name}.db"
        return optuna.create_study(
            study_name=sweep_name,
            storage=storage_name,
            pruner=pruner,
            load_if_exists=True,
        )

    def _start(self) -> None:
        for worker_id in range(self._num_workers):
            print(f"{LOG_PREFIX}Starting AgentHeartbeat worker {worker_id}\n")
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

        print(f"{LOG_PREFIX}OptunaHeartbeat sending: \n")
        commands: List[Dict[str, Any]] = self._optuna_heartbeat(
            self._workers[worker_id].agent_id,  # agent_id: str
            _run_states,  # run_states: dict
        )
        print(f"{LOG_PREFIX}OptunaHeartbeat received {len(commands)} commands: \n")

        for command in commands:
            _type = command.get("type")
            if _type == "stop":
                self.state = SchedulerState.STOPPED
                self.exit()
                return
            elif _type in ["run", "resume"]:
                _run_id = command.get("run_id")
                if _run_id is None:
                    self.state = SchedulerState.FAILED
                    raise SchedulerError(
                        f"AgentHeartbeat command {command} missing run_id"
                    )
                if _run_id in self._runs:
                    print(f"{LOG_PREFIX} Skipping duplicate run {run_id}")
                else:
                    run = SweepRun(
                        id=_run_id,
                        args=command.get("args", {}),
                        logs=command.get("logs", []),
                        program=command.get("program"),
                        worker_id=worker_id,
                    )
                    self._runs[run.id] = run
                    self._heartbeat_queue.put(run)
            else:
                self.state = SchedulerState.FAILED
                raise SchedulerError(f"AgentHeartbeat unknown command type {_type}")

    def _run(self) -> None:
        # Go through all workers and heartbeat
        for worker_id in self._workers.keys():
            self._heartbeat(worker_id)

        try:
            run: SweepRun = self._heartbeat_queue.get(
                timeout=self._heartbeat_queue_timeout
            )
        except queue.Empty:
            print(f"{LOG_PREFIX}No jobs in Sweeps RunQueue, waiting...")
            time.sleep(self._heartbeat_queue_sleep)
            return
        # If run is already stopped just ignore the request
        if run.state in [
            SimpleRunState.DEAD,
            SimpleRunState.UNKNOWN,
        ]:
            return
        print(f"{LOG_PREFIX}Converting Sweep Run (RunID:{run.id}) to Launch Job")

    def make_trial(self, trial):
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

    def _optuna_heartbeat(
        self, agent_id: str, _run_states: Dict[str, bool]
    ) -> List[Dict[str, Any]]:
        def objective(trial):

            sweep_config, trial = self.make_trial(trial)
            print(f"in objective with trial params: {trial.params=}")

            run: Run = wandb.init(
                project=self._project,
                entity=self._entity,
                job_type="sweep_run",
                config=trial.params,  # json.dumps(trial.params)
            )

            program = self._sweep_config.get("program")

            sweep_run = SweepRun(
                id=run.id,
                args=run.config,
                logs=[],
                program=program,
                worker_id=agent_id,
            )
            self._runs[sweep_run.id] = sweep_run
            self._heartbeat_queue.put(sweep_run)

            _ = self._add_to_launch_queue(
                run_id=run.id,
                entry_point=["python3", program],
                # Use legacy sweep utilities to extract args dict from agent heartbeat run.args
                config={
                    "overrides": {
                        "run_config": LegacySweepAgent._create_command_args(
                            {"args": sweep_config}
                        )["args_dict"]
                    },
                    "resource": "local-process",
                },
            )

            api_run = self._public_api.run(run.path)
            last_epoch = 0
            while True:
                # print(f"top of while true: {api_run.state=}, {api_run.id=}")

                # TODO: support other metrics
                history = api_run.scan_history(keys=["_step", "loss_metric"])
                # print(f"hist: {[x for x in history]}")

                next_epochs = [x for x in history if x["_step"] > last_epoch]

                if len(next_epochs) == 0:
                    print(".")
                    time.sleep(1)
                    continue

                # nothing fancy, just log all steps
                for epoch_data in next_epochs:
                    print(f"{epoch_data['_step']}: {epoch_data['loss_metric']}")
                    trial.report(
                        epoch_data["loss_metric"], epoch_data["_step"]
                    )  # todo fix metric

                last_epoch = epoch_data["_step"]

                if trial.should_prune():
                    print("Optuna decided to PRUNE, sending STOP!")
                    run.finish()
                    encoded = base64.standard_b64encode(
                        f"Run:v1:{api_run.id}:{self._project}:{self._entity}".encode()
                    ).decode("utf-8")
                    self._internal_api._stop_run(encoded)
                    raise optuna.TrialPruned()

                if epoch_data["_step"] == trial.params["epochs"] - 1:
                    print("DONE!")
                    run.finish()
                    return epoch_data["loss_metric"]
            return -1

        self.study.optimize(objective, n_trials=10, n_jobs=1)

        # command = {
        #     "id": run.id,
        #     "type": "run",
        #     "state": SimpleRunState.ALIVE,
        #     "args": params,
        #     "worker_id": agent_id,
        # }

        return {}
