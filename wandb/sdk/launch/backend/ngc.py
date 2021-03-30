import copy
import json
import logging
import os
import sys
import time

import wandb

from .abstract import AbstractBackend, AbstractRun, Status

_logger = logging.getLogger(__name__)


class NGCSubmittedRun(AbstractRun):
    """
    Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point
    command locally.
    """

    STATE_MAP = {
        "COMPLETED": "finished",
        "FINISHED_SUCCESS": "finished",
        "FAILED": "failed",
        "RUNNING": "running",
    }
    POLL_INTERVAL = 30  # TODO: backoff?

    def __init__(self, run_id, cmd):
        super().__init__(run_id)
        data = self._parse_cmd(self._run_cmd(cmd))
        self._status = Status(self.STATE_MAP.get(data.get("status"), "starting"), data)
        self._last_poll = time.time()

    @property
    def id(self):
        return self._job_id

    def wait(self):
        while True:
            if self.get_status() not in ("finished", "failed"):
                time.sleep(self.POLL_INTERVAL)
            else:
                break

    def cancel(self):
        parsed = self._parse_cmd(
            self._run_cmd(
                ["ngc", "batch", "kill", str(self._job_id), "--format_type", "json"]
            )
        )
        if parsed:
            return True  # TODO: more here.

    def _update_status(self, force=False):
        if force or time.time() - self._last_poll >= self.POLL_INTERVAL:
            parsed = self._parse_cmd(
                self._run_cmd(
                    ["ngc", "batch", "info", str(self._job_id), "--format_type", "json"]
                )
            )
            if parsed:
                try:
                    self._status.state = self.STATE_MAP.get(
                        parsed.get("status"), "starting"
                    )
                    self._status.data = parsed  # TODO: is this needed?
                except (ValueError, TypeError):
                    wandb.termerror("Parse Error: {}".format(parsed))

    def _parse_cmd(self, popen):
        popen.wait()
        try:
            parsed = json.loads(popen.stdout.read(), encoding="utf-8")
            if parsed and parsed.get("id"):
                self._job_id = parsed.get("id")
                return parsed.get("jobStatus", {})
            return None
        except (ValueError, TypeError) as e:
            wandb.termerror("Failure: {}".format(e))
            return None

    def get_status(self):
        self._update_status()
        return self._status.state


class NGCBackend(AbstractBackend):
    PREFIX = "wget -qO - https://wandb.me/ngc | bash && WANDB_API_KEY={} {}"
    DEFAULT_CFG = {
        "image": os.getenv(
            "NGC_IMAGE", "nvidia/tensorflow:21.02-tf2-py3"
        ),  # "nvidia/pytorch:19.10-py3"),
        "datasetid": os.getenv("NGC_DATASET_ID", None),
        "jobid": os.getenv("NGC_JOB_ID", None),
        "name": os.getenv("NGC_NAME", "wandb run"),
        "instance": os.getenv("NGC_INSTANCE", "dgx1v.32g.1.norm"),
        "replicas": os.getenv("NGC_REPLICAS", "1"),
        "command": None,
    }

    def _generate_cmd(self, backend_config):
        cfg = copy.copy(self.DEFAULT_CFG)
        cfg.update(backend_config)  # TODO: this used to call into "ngc"
        # TODO: use / setup these for running in NGC
        # use_conda = backend_config[PROJECT_USE_CONDA]
        # docker_args = backend_config[PROJECT_DOCKER_ARGS]
        # storage_dir = backend_config[PROJECT_STORAGE_DIR]
        container_cmd = self.PREFIX.format(
            self.api_key, cfg["command"] or "wandb status"
        )
        cmd = [
            "ngc",
            "batch",
            "run",
            "--format_type",
            "json",
            "--result",
            "/result",
            "-in",
            cfg["instance"],
            "-n",
            cfg["name"],
            "-i",
            cfg["image"],
            "--commandline",
            container_cmd,
        ]
        if cfg["datasetid"]:
            cmd = cmd.append(["--datasetid", cfg["datasetid"]])
        return cmd

    def verify(self):
        super().verify()
        if not self.find_executable("ngc"):
            wandb.termerror("couldn't find ngc executable")
            sys.exit(1)
        return True

    def run(
        self, project_uri, entry_point, params, version, backend_config, experiment_id
    ):
        run_id = os.getenv("WANDB_RUN_ID")  # TODO: bad
        #  TODO: eventually we may want to require a project, for now we don't
        project = self.fetch_and_validate_project(
            project_uri, version, entry_point, params
        )

        # Build a docker image here?
        if project.docker_env:
            pass

        cmd = self._generate_cmd(backend_config)
        return NGCSubmittedRun(run_id, cmd)
