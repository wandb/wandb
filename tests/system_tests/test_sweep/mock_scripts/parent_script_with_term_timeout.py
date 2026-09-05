import os
import queue
import signal
import sys
import threading
import time

import wandb.wandb_agent as wandb_agent
from wandb.wandb_agent import Agent

child_script = sys.argv[1]
term_timeout = int(sys.argv[2])

wandb_agent._sweep_with_runs = lambda api, sweep_id, spec: None
wandb_agent._register_agent = lambda api, host, sweep_id=None: {"id": "agent-1"}
wandb_agent._agent_heartbeat = lambda api, agent_id, spec, run_status: []


# Seed agent command queue to run the child script
command_queue = queue.Queue()
command_queue.put(
    {
        "type": "run",
        "run_id": "run-1",
        "program": child_script,
        "args": {},
        "resp_queue": queue.Queue(),
    }
)

agent = Agent(
    None,
    command_queue,
    sweep_id="sweep-1",
    term_timeout=term_timeout,
    forward_signals=True,
)

# Send a SIGINT after 1 second. This is eaten by then child process but
# puts the Agent into the tier 1 waiting state.
threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGINT)).start()

start = time.monotonic()
agent.run()
elapsed = time.monotonic() - start

procs = list(agent._run_processes.values())
child = procs[0]

returncode = child.wait(timeout=5)
if returncode != -signal.SIGKILL:
    sys.exit(2)

# We expect that the child terminated roughly around the term_timeout time
if elapsed > term_timeout * 3:
    sys.exit(3)
if elapsed < term_timeout * 0.5:
    sys.exit(4)
