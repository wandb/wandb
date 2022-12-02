from typing import Any, Dict, List
import wandb
from dataclasses import dataclass

from collections import defaultdict

import time
import socket
import optuna
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
from wandb.wandb_agent import Agent as LegacySweepAgent

from wandb.apis.public import Api, QueuedRun
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
        self._public_api = Api()
        self._internal_api = InternalApi()

    def _exit(self) -> None:
        pass

    def _load_db(self, study_name: str = None):
        """
        Create an optuna study with a sqlite backened for loose state management
        """
        # TODO(gst): add to validate function to confirm this exists, warn user
        if not study_name:
            study_name = f"optuna-study-{self._sweep_id}"

        params = self._sweep_config.get("parameters", {})
        epochs = params.get("epochs", {}).get("value") or 20
        pruner_args = params.get("pruner", {})

        print(
            f"{LOG_PREFIX}Creating study: {study_name} with HyperbandPruner w/ {epochs=}"
        )
        pruner = optuna.pruners.HyperbandPruner(
            min_resource=pruner_args.get(
                "min_resource", 1
            ),  # TODO(gst): defaults are from tutorial
            max_resource=epochs,
            reduction_factor=pruner_args.get("reduction_factor", 3),
        )

        storage_name = f"sqlite:///{study_name}.db"
        return optuna.create_study(
            study_name=study_name,
            storage=storage_name,
            pruner=pruner,
            load_if_exists=True,
        )

    def _start(self) -> None:
        print(f"{LOG_PREFIX}Starting AgentHeartbeat worker {0}\n")
        agent_config = self._api.register_agent(
            f"{socket.gethostname()}-{0}",  # host
            sweep_id=self._sweep_id,
            project_name=self._project,
            entity=self._entity,
        )
        self._workers[0] = _Worker(
            agent_config=agent_config,
            agent_id=agent_config["id"],
        )

    def _heartbeat(self, worker_id: int) -> None:
        # Make sure Scheduler is alive
        if not self.is_alive():
            return

        commands: List[Dict[str, Any]] = self._optuna_heartbeat(
            self._workers[worker_id].agent_id,
        )

        for command in commands:
            _type = command.get("type")
            if _type == "stop":
                self.state = SchedulerState.STOPPED
                self.exit()
                return
            # elif _type in ["run", "resume"]:
            #     _run_id = command.get("run_id")
            #     if _run_id is None:
            #         self.state = SchedulerState.FAILED
            #         raise SchedulerError(
            #             f"AgentHeartbeat command {command} missing run_id"
            #         )
            #     if _run_id in self._runs:
            #         print(f"{LOG_PREFIX} Skipping duplicate run {_run_id}")
            #     else:
            #         run = SweepRun(
            #             id=_run_id,
            #             args=command.get("args", {}),
            #             logs=command.get("logs", []),
            #             program=command.get("program"),
            #             worker_id=worker_id,
            #         )
            #         self._runs[run.id] = run
            #         self._heartbeat_queue.put(run)
            else:
                self.state = SchedulerState.FAILED
                raise SchedulerError(f"AgentHeartbeat unknown command type {_type}")

    def _run(self) -> None:
        # Go through all 1 worker and heartbeat
        self._heartbeat(0)
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

    def _optuna_heartbeat(self, agent_id: str) -> List[Dict[str, Any]]:
        def objective(trial):
            """Optuna objective function"""
            sweep_config, trial = self.make_trial(trial)
            queued_run: QueuedRun = self._add_to_launch_queue(
                entry_point=[
                    f"WANDB_SWEEP_ID={self._sweep_id} python3",
                    self._sweep_config.get("program"),
                ],
                # Use legacy sweep utilities to extract args dict from agent heartbeat run.args (?)
                config={
                    "overrides": {
                        "run_config": LegacySweepAgent._create_command_args(
                            {"args": sweep_config}
                        )["args_dict"],
                    },
                    "resource": "local-process",
                },
            )

            # wait for launch to actually create a run object
            launched_run = queued_run.wait_until_running()
            launched_run_path = "/".join(launched_run.path)

            encoded_run_id = base64.standard_b64encode(
                f"Run:v1:{launched_run.id}:{self._project}:{self._entity}".encode()
            ).decode("utf-8")

            api_run = self._public_api.run(launched_run_path)
            # Set external runs sweep information
            self._internal_api.upsert_run(id=encoded_run_id, sweep_name=self._sweep_id)

            last_epoch = -1
            while True:
                history = api_run.scan_history(keys=["_step", "loss_metric"])
                next_epochs = [x for x in history if x["_step"] > last_epoch]

                if len(next_epochs) == 0:
                    time.sleep(1)
                    continue

                for epoch_data in next_epochs:
                    step = epoch_data["_step"]
                    loss = epoch_data["loss_metric"]
                    sweep_job.log({"step": step, "loss": loss})
                    print(f"{LOG_PREFIX}Step {step}: loss={loss}")
                    trial.report(loss, step)  # todo fix metric

                last_epoch = step
                if trial.should_prune():
                    print(f"{LOG_PREFIX}Optuna decided to PRUNE!")
                    success = self._internal_api._stop_run(encoded_run_id)
                    if success:
                        print(f"{LOG_PREFIX}Stopped run: {api_run.id}")
                    else:
                        print(f"{LOG_PREFIX}Couldn't stop run...")

                    raise optuna.TrialPruned()

                if last_epoch == trial.params["epochs"] - 1:
                    print(f"{LOG_PREFIX} Trial completed!")
                    sweep_job.log({"loss": loss})
                    return loss

        """ Create master sweep job here """
        settings = wandb.Settings()
        settings.update({"enable_job_creation": True})
        sweep_job = wandb.init(
            settings=settings,
            project=self._project,
            entity=self._entity,
            job_type="sweep_run",
        )
        sweep_job.log_code()
        self.study.optimize(objective, n_trials=5, n_jobs=self._num_workers)
        sweep_job.finish()

        return [{"type": "stop"}]


"""
Currently we create a new run in the objective function process,
but we really want to delay that until in the launched run, so that
we can have a master scheduler run/job, and the spawned runs
report back to it.

"""
