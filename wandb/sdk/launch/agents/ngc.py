# -*- coding: utf-8 -*-
"""NGC Agent

A custom agent for Nvidia NGC
"""

import os
import copy
import json
import sys

from .abstract_agent import BaseAgent, Status

import wandb


class NGCAgent(BaseAgent):
    STATE_MAP = {
        "COMPLETED": "finished",
        "FINISHED_SUCCESS": "finished",
        "FAILED": "failed",
        "RUNNING": "running",
    }
    PREFIX = "wget -qO - https://wandb.me/ngc | bash && WANDB_API_KEY={} {}"
    DEFAULTS = {
        "image": os.getenv("NGC_IMAGE", "nvidia/pytorch:19.10-py3"),
        "datasetid": os.getenv("NGC_DATASET_ID", None),
        "jobid": os.getenv("NGC_JOB_ID", None),
        "name": os.getenv("NGC_NAME", "wandb run"),
        "instance": os.getenv("NGC_INSTANCE", "dgx1v.32g.1.norm"),
        "replicas": os.getenv("NGC_REPLICAS", "1"),
        "command": None,
    }

    def verify(self):
        if not self.find_executable("ngc"):
            wandb.termerror("NGC not installed, install it from https://ngc.nvidia.com")
            sys.exit(1)

    def _setup_cmd(self, spec):
        cfg = copy.copy(self.DEFAULTS)
        cfg.update(spec.get("ngc", {}))
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

    def _parse_cmd(self, popen):
        popen.wait()
        try:
            parsed = json.loads(popen.stdout.read(), encoding="utf-8")
            if parsed:
                job_id = parsed.get("id")
                if job_id is not None:
                    data = parsed.get("jobStatus", {})
                    self._jobs[job_id] = Status(self.STATE_MAP.get(data["status"], "starting"), data)
                    return job_id
            return None
        except (ValueError, TypeError) as e:
            wandb.termerror("Failure: {}".format(e))
            return None

    def _update_status(self):
        for job_id in self.job_ids:
            parsed = self._run_cmd(["ngc", "batch", "info", str(job_id), "--format_type", "json"], output_only=True)
            if parsed:
                try:
                    parsed = json.loads(parsed, encoding="uft-8")
                    data = parsed.get("jobStatus", {})
                    self._jobs[job_id] = Status(self.STATE_MAP.get(data["status"], "starting"), data)
                except (ValueError, TypeError) as e:
                    wandb.termerror(str(e))
