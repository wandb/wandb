import os
import copy
import shlex
import sys

import wandb

from .abstract_agent import BaseAgent, Status


class DockerAgent(BaseAgent):
    STATE_MAP = {
        "exited": "finished",
        "dead": "failed",
        "running": "running",
    }
    DEFAULTS = {
        "image": os.getenv("DOCKER_IMAGE", "ufoym/deepo"),
        "args": os.getenv("DOCKER_ARGS", None),
        "command": None,
    }

    def verify(self):
        if not self.find_executable("docker"):
            wandb.termerror("Docker not installed, install it from https://docker.com")
            sys.exit(1)

    def name(self):
        return "wandb-run-{}-{}".format(len(self._jobs), self._namespace)

    def _setup_cmd(self, spec):
        cfg = copy.copy(self.DEFAULTS)
        cfg.update(spec.get("docker", {}))
        container_cmd = cfg["command"] or "wandb status"
        name = self.name()
        cmd = [
            "wandb",
            "docker-run",
            "-d",
            "--name",
            name
        ]
        if cfg["args"]:
            cmd = cmd.append(shlex.split(cfg["args"]))
        cmd = cmd.append([cfg["image"], container_cmd])
        return cmd

    def _parse_cmd(self, popen):
        popen.wait()
        try:
            job_id = popen.stdout.read().encode("utf-8")
            if job_id is not None:
                self._jobs[job_id] = Status("starting")
                return job_id
            return None
        except (ValueError, TypeError) as e:
            wandb.termerror("Failure: {}".format(e))
            return None

    def _update_status(self):
        for job_id in self.job_ids:
            parsed = self._run_cmd(["docker", "inspect", "--format", '{{json .State}}', str(job_id)], output_only=True)
            if parsed:
                self._jobs[job_id] = Status(self.STATE_MAP.get(parsed.get("Status"), "starting"))
