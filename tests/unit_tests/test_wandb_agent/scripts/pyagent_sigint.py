"""Run a mocked pyagent job until the parent sends SIGINT.

For use with test_pyagent.py::test_pyagent_sigint_finishes_run_before_teardown.
"""

import time
from unittest import mock

import wandb
import wandb.agents.pyagent as pyagent


def main() -> None:
    api = mock.MagicMock()
    api.register_agent.return_value = {"id": "agent"}
    api.agent_heartbeat.side_effect = [
        [{"type": "run", "run_id": "sigint-run", "args": {"a": {"value": 1}}}]
    ] + [[]] * 1000

    wandb.Api = lambda *args, **kwargs: api
    pyagent._register_agent = lambda _api, *args, **kwargs: _api.register_agent(
        *args, **kwargs
    )
    pyagent._agent_heartbeat = lambda _api, *args, **kwargs: _api.agent_heartbeat(
        *args, **kwargs
    )
    pyagent.Agent.HEARTBEAT_SLEEP_SECONDS = 0.05

    def finish(exit_code=None, **kwargs):
        # Slow enough that a teardown not waiting for the job is seen first.
        time.sleep(0.5)
        print(f"finish {exit_code}", flush=True)

    wandb.finish = finish
    wandb.teardown = lambda *args, **kwargs: print("teardown", flush=True)

    def train():
        print("training", flush=True)
        while True:
            time.sleep(0.01)

    pyagent.Agent(
        sweep_id="sweep-sigint",
        entity="entity",
        project="project",
        function=train,
        count=1,
    ).run()
    print("done", flush=True)


if __name__ == "__main__":
    main()
