import wandb
from wandb import env
import os
import traceback
import time
import sys

# TODO: this is LAME
RUNS = {}
LOG_FLUSH_MINIMUM = 5
_IS_WANDB_MODULE = True


def patch():
    mlflow = wandb.util.get_module("mlflow")
    # TODO: really hacky, is happening from internal_cli.py for some reason
    if hasattr(mlflow, "_IS_WANDB_MODULE"):
        return False
    if os.getenv(env.SYNC_MLFLOW) in ["false", "0", "none"] or mlflow is None or len(wandb.patched["mlflow"]) > 0:
        return False
    from mlflow.tracking.client import MlflowClient
    # was seeing infinite recursion in pytest
    if hasattr(MlflowClient, "orig_log_metric"):
        return False

    from mlflow.tracking import fluent
    client = MlflowClient()

    orig_start_run = fluent.start_run
    orig_end_run = fluent.end_run
    MlflowClient.orig_log_metric = MlflowClient.log_metric
    MlflowClient.orig_log_param = MlflowClient.log_param
    MlflowClient.orig_set_tag = MlflowClient.set_tag
    MlflowClient.orig_log_batch = MlflowClient.log_batch
    MlflowClient.orig_log_artifact = MlflowClient.log_artifact
    MlflowClient.orig_log_artifacts = MlflowClient.log_artifacts

    def _get_or_start_wandb_run(run, run_id=None, name=None):
        try:
            os.environ[env.SILENT] = "1"
            os.environ[env.SYNC_MLFLOW] = os.getenv(env.SYNC_MLFLOW, "all")
            if run_id:
                os.environ[env.RESUME] = "allow"  # TODO: must?
            if run.data.tags.get("mlflow.parentRunId"):
                parent = RUNS.get(run.data.tags["mlflow.parentRunId"], {"run": None})["run"]
                if parent and parent.group is None:
                    parent.group = run.data.tags["mlflow.parentRunId"]
                    parent.job_type = "parent"
                    parent.save()
                #TODO: maybe call save
                os.environ[env.RUN_GROUP] = run.data.tags["mlflow.parentRunId"]
                os.environ[env.JOB_TYPE] = "child"

            project = os.getenv(env.PROJECT, client.get_experiment(run.info.experiment_id).name)
            config = run.data.tags
            config["mlflow.tracking_uri"] = mlflow.get_tracking_uri()
            config["mlflow.experiment_id"] = run.info.experiment_id
            wandb_run = RUNS.get(run.info.run_id)
            if wandb_run is None:
                wandb_run = wandb.init(id=run.info.run_id, project=project,
                                       name=name, config=config, reinit=True)

            wandb.termlog("Syncing MLFlow metrics, params, and artifacts to: %s" %
                          wandb_run.get_url().split("/runs/")[0], repeat=False, force=True)
            wandb_run.config._set_wandb('mlflow_version', mlflow.__version__)
            RUNS[wandb_run.id] = {"step": 0, "last_log": time.time(), "run": wandb_run}
            return wandb_run
        except Exception as e:
            wandb.termerror("Failed to intialize wandb, disable by setting WANDB_SYNC_MLFLOW=false", force=True)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            print('\n'.join(lines))

    def start_run(**kwargs):
        run = orig_start_run(**kwargs)
        _get_or_start_wandb_run(run, run_id=kwargs.get("run_id"), name=kwargs.get("run_name"))
        return run
    fluent.start_run = start_run
    mlflow.start_run = start_run

    def end_run(status):
        # TODO: use status and switch to set_terminated for joining the run
        orig_end_run(status)
        wandb.join(0 if status == "FINISHED" else 1)
    fluent.end_run = end_run
    mlflow.end_run = end_run

    def _get_run(run_id, only_run=True):
        run = RUNS.get(run_id, {}).get("run") if only_run else RUNS.get(run_id, {})
        if not run:
            wandb.termwarn("No run found for %s - cur: %s" % (run_id, wandb.run), force=True)
            run = MlflowClient().get_run(run_id)
            return _get_or_start_wandb_run(run)
        else:
            return run

    def log_param(self, run_id, key, value):
        MlflowClient.orig_log_param(self, run_id, key, value)
        _get_run(run_id).config[key] = value
    MlflowClient.log_param = log_param

    def set_tag(self, run_id, key, value):
        MlflowClient.orig_set_tag(self, run_id, key, value)
        _get_run(run_id).config[key] = value
    MlflowClient.set_tag = set_tag

    def _fix_step(run_id, metrics, step, timestamp):
        """Handle different steps by namespacing a new step counter with the first key
            if global step decreases.  Also auto increase step if we're it's not increasing
            every LOG_FLUSH_MINIMUM seconds TODO: make this actually work"""
        key = list(metrics)[0]
        run_log = _get_run(run_id, False)
        if step in (None, 0) and int(time.time() - run_log["last_log"]) > LOG_FLUSH_MINIMUM:
            wandb.termwarn("Metric logged without a step, pass a step to log_metric.", repeat=False)
            step = run_log["step"] + 1

        # Run with multiple steps, keeping a seperate step count
        if step < run_log["step"]:
            metrics[key+"/step"] = step
            step = run_log["step"]

        if step != run_log["step"]:
            run_log["step"] = step
            run_log["last_log"] = time.time()

        return metrics, step

    def log_metric(self, run_id, key, value, timestamp=None, step=None):
        MlflowClient.orig_log_metric(self, run_id, key, value, timestamp, step)
        metrics, step = _fix_step(run_id, {key: value}, step, timestamp)
        _get_run(run_id).history.add(metrics, step=step)
    MlflowClient.log_metric = log_metric

    def log_batch(self, run_id, metrics=(), params=(), tags=()):
        MlflowClient.orig_log_batch(self, run_id, metrics, params, tags)
        run = _get_run(run_id)
        for metric in metrics:
            metrics, step = _fix_step(run_id, {metric.key: metric.value}, metric.step, metric.timestamp)
            run.history.add(metrics, step=step)
        for conf in (params + tags):
            run.config[conf.key] = conf.value
    MlflowClient.log_batch = log_batch

    def log_artifact(self, run_id, local_path, artifact_path=None):
        MlflowClient.orig_log_artifact(self, run_id, local_path, artifact_path)
        if os.getenv(env.SYNC_MLFLOW) != "all":
            return
        if os.path.isdir(local_path):
            filename = ""
        else:
            filename = os.path.basename(local_path)
        run = _get_run(run_id)
        wandb_path = os.path.abspath(os.path.join(run.dir, artifact_path or "", filename))
        if not os.path.exists(wandb_path):
            os.symlink(os.path.abspath(local_path), wandb_path)
    MlflowClient.log_artifact = log_artifact

    def log_artifacts(self, run_id, local_dir, artifact_path=None):
        MlflowClient.orig_log_artifacts(self, run_id, local_dir, artifact_path)
        if os.getenv(env.SYNC_MLFLOW) != "all":
            return
        #TODO: abspath?
        run = _get_run(run_id)
        wandb_path = os.path.abspath(os.path.join(run.dir, artifact_path or ""))
        if not os.path.exists(wandb_path):
            os.symlink(os.path.abspath(local_dir), wandb_path)
    MlflowClient.log_artifacts = log_artifacts
    #TODO: store all patches
    wandb.patched["mlflow"].append(["mlflow.tracking.client", "MlflowClient.log_artifacts"])

    return True
