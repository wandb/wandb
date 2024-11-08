import wandb
from kubernetes import client, config

import json
import os
import time
import hashlib


WANDB_API_KEY = os.getenv("WANDB_API_KEY")


def create_job_object(entity: str, project: str, sweep_id: str, run_id: str, config: str):
    # Configure Pod template container
    container = client.V1Container(
        name="sweep-run",
        image="jzhaowandb/sweep_train:v4",
        env=[
            client.V1EnvVar(name="WANDB_API_KEY", value=WANDB_API_KEY),
            client.V1EnvVar(name="WANDB_ENTITY", value=entity),
            client.V1EnvVar(name="WANDB_PROJECT", value=project),
            client.V1EnvVar(name="WANDB_SWEEP_ID", value=sweep_id),
            client.V1EnvVar(name="WANDB_RUN_ID", value=run_id),
            # don't do this in prod, there are better ways to pass config
            client.V1EnvVar(name="CONFIG", value=config),
        ]
    )
    # Create and configure a spec section
    template = client.V1PodTemplateSpec(
        spec=client.V1PodSpec(restart_policy="OnFailure", containers=[container]))
    # Create the specification of deployment
    spec = client.V1JobSpec(
        template=template,
        backoff_limit=5)
    # Instantiate the job object
    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=run_id),
        spec=spec)

    return job


def create_job(api_instance, job):
    api_response = api_instance.create_namespaced_job(
        body=job,
        namespace="default")
    print(f"Job created. status='{str(api_response.status)}'")
    get_job_status(api_instance, job.metadata.name)


def get_job_status(api_instance, name: str):
    job_completed = False
    while not job_completed:
        api_response = api_instance.read_namespaced_job_status(
            name=name,
            namespace="default")
        if api_response.status.succeeded is not None or \
                api_response.status.failed is not None:
            job_completed = True
        time.sleep(1)
        print(f"Job status='{str(api_response.status)}'")

def generate_run_id(config: dict):
    # Create stable hash of config dict for run ID
    config_str = json.dumps(config, sort_keys=True)
    return f"custom-{hashlib.md5(config_str.encode()).hexdigest()[:8]}"


config.load_kube_config()
batch_v1 = client.BatchV1Api()
run = wandb.init(job_type="controller")
entity = run.entity
project = run.project
run_id = generate_run_id(dict(run.config))

print(run_id)
print(run.sweep_id)

job = create_job_object(entity, project, run.sweep_id, run_id, json.dumps(dict(run.config)))
create_job(batch_v1, job)


