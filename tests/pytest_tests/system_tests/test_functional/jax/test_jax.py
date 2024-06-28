import pathlib

import pytest


@pytest.mark.wandb_core_only
def test_log_bfloat16(user, relay_server, execute_script):
    with relay_server() as relay:
        return_code = execute_script(
            pathlib.Path(__file__).parent / "01-log-bfloat16.py"
        )
        print("Return code:", return_code)

        run_history = relay.context.history
        print("Run history:", run_history)

    # TODO: convert to assert statements


"""
id: 0.jax.01-log-bfloat16
tag:
  platforms:
    - linux
    - mac
  shard: jax
plugin:
  - wandb
depend:
  requirements:
    - jax
    - jaxlib
    - numpy
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      m1: 1
      m2: 2
      m3:
        - 3
        - 4
  - :wandb:runs[0][exitcode]: 0
"""
