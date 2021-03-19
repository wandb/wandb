import os

from .abstract_agent import BaseAgent, Status


class LocalAgent(BaseAgent):
    REMOTE = False

    def _setup_cmd(self, spec):
        return spec.get("command", ["python", "train.py"])

    def _parse_cmd(self, popen):
        self._jobs[str(popen.pid)] = Status("starting", {"proc": popen})
        self._update_status()
        return str(popen.pid)

    def _update_status(self):
        for pid, status in self.job_ids:
            res = status.data["proc"].poll()
            if res is None:
                status.state = "running"
            elif res == 0:
                status.state = "finished"
            else:
                status.state = "failed"
