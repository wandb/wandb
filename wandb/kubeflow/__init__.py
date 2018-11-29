import datetime
import json
import os
import logging
import requests
import subprocess
import six
import time
import yaml
import wandb
import sys
from wandb import util
from wandb import Api
storage = util.get_module("google.cloud.storage")


def _upload_wandb_webapp(gcs_path, wandb_run_path):
    # TODO: Check if we're local and change the url
    # We can use this once my pull is approved
    # client = Minio('minio-service.kubeflow:9000',
    #               access_key='minio',
    #               secret_key='minio123',
    #               secure=False)
    #client.fput_object('mlpipeline', wbpath, "wandb.html")
    wandb_path = os.path.join("artifacts", wandb_run_path, "wandb.html")
    output_path = os.path.join(gcs_path, wandb_path)
    _, _, bucket, key = output_path.split("/", 3)
    blob = storage.Client().get_bucket(bucket).blob(key)

    template = os.path.join(os.path.dirname(
        os.path.realpath(__file__)), "wandb.template.html")
    blob.upload_from_string(
        open(template).read().replace("$RUN_PATH", wandb_run_path))
    return output_path


def pipeline_metadata(gcs_url, wandb_run_path=None, tensorboard=True):
    if not gcs_url.startswith("gs://"):
        print("Tensorboard and W&B artifacts require --logdir to be a GCS url")
    elif wandb_run_path and os.path.exists("/argo/podmetadata"):
        web_app_source = _upload_wandb_webapp(
            gcs_url, wandb_run_path)

        outputs = [{
            'type': 'web-app',
            'source': web_app_source
        }]
        if tensorboard:
            outputs.append({
                'type': "tensorboard",
                'source': gcs_url,
            })
        with open('/mlpipeline-ui-metadata.json', 'w') as f:
            json.dump({'outputs': outputs}, f)
        print("KubeFlow pipeline assets saved")


def arena_launcher_op(image, command, type="tfjob", gpus=0, env=[], workers=1, logdir=None,
                      parameter_servers=0, timeout_minutes=10, sync_source=None,
                      name=None, wandb_project=None, wandb_run_id=None):
    from kfp import dsl
    options = []
    if name:
        options.extend(['--name', name])
    if logdir:
        options.extend(['--logdir', logdir])
    if sync_source:
        if not sync_source.startswith("http"):
            raise ValueError("sync_source must be an http git url")
        options.extend(["--syncSource", sync_source])
    if wandb_project:
        options.extend(['--wandb-project', wandb_project])
    if wandb_run_id:
        options.extend(['--wandb-run_id', wandb_run_id])
    for e in env:
        options.extend(['--env', e])
    op = dsl.ContainerOp(
        name=name,
        image='wandb/arena',
        arguments=[
            '--workers', workers,
            '--pss', parameter_servers,
            '--timeout-minutes', timeout_minutes,
            '--image', image,
            '--logdir', logdir,
        ] + options + [" ".join(command)],
        file_outputs={'train': '/output.txt'}
    )
    key = Api().api_key
    if key is None:
        raise ValueError("Not logged into W&B, run `wandb login`")
    op.add_env_variable({"WANDB_API_KEY": key})
    return op
