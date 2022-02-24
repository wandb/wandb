import os
import random

import wandb
from kubernetes.client.models import V1EnvVar
from wandb.integration.kfp import wandb_log

import kfp
import kfp.dsl as dsl
from kfp import components


def add_wandb_env_variables(op):
    env = {
        "WANDB_API_KEY": os.environ["WANDB_API_KEY"],
        "WANDB_BASE_URL": os.environ["WANDB_BASE_URL"],
        "WANDB_PROJECT": "wandb_kfp_integration_test",
    }

    for name, value in env.items():
        op = op.add_env_variable(V1EnvVar(name, value))
    return op


@wandb_log
def add(a: float, b: float) -> float:
    return a + b


add = components.create_component_from_func(add)


@dsl.pipeline(name="adding-pipeline")
def testing_pipeline(seed: int, a: float, b: float):
    conf = dsl.get_pipeline_conf()
    conf.add_op_transformer(add_wandb_env_variables)
    add_task = add(a, b)
    add_task2 = add(add_task.output, add_task.output)


client = kfp.Client()
run = client.create_run_from_pipeline_func(
    testing_pipeline,
    arguments={
        "seed": random.randint(0, 999999),
        "a": random.random(),
        "b": random.random(),
    },
)

run.wait_for_run_completion()
