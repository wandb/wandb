import os
import random

import kfp
import kfp.dsl as dsl
from kfp import components
from kubernetes.client.models import V1EnvVar
from wandb.integration.kfp import wandb_log
from wandb_probe import wandb_probe_package


def add_wandb_env_variables(op):
    env = {
        "WANDB_API_KEY": os.getenv("WANDB_API_KEY"),
        "WANDB_BASE_URL": os.getenv("WANDB_BASE_URL"),
        "WANDB_KUBEFLOW_URL": os.getenv("WANDB_KUBEFLOW_URL"),
        "WANDB_PROJECT": "wandb_kfp_integration_test",
    }

    for name, value in env.items():
        op = op.add_env_variable(V1EnvVar(name, value))
    return op


@wandb_log
def add(a: float, b: float) -> float:
    return a + b


packages_to_install = []
# probe wandb dev build if needed (otherwise released wandb will be used)
wandb_package = wandb_probe_package()
if wandb_package:
    print("INFO: wandb_probe_package found:", wandb_package)
    packages_to_install.append(wandb_package)
add = components.create_component_from_func(
    add,
    packages_to_install=packages_to_install,
)


@dsl.pipeline(name="adding-pipeline")
def testing_pipeline(seed: int, a: float, b: float):
    conf = dsl.get_pipeline_conf()
    conf.add_op_transformer(add_wandb_env_variables)
    add_task = add(a, b)
    add_task2 = add(add_task.output, add_task.output)  # noqa: F841


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
