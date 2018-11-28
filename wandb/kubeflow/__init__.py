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
from wandb.kubeflow import tf_job_client
storage = util.get_module("google.cloud.storage")


def _generate_train_yaml(src_filename, tfjob_ns, workers, pss, trainer_image, command, gpus):
    """_generate_train_yaml  generates train yaml files based on train.template.yaml"""
    path = os.path.join(os.path.dirname(
        os.path.realpath(__file__)), src_filename)
    with open(path, 'r') as f:
        content = yaml.load(f)

    content['metadata']['generateName'] = 'trainer-'
    content['metadata']['namespace'] = tfjob_ns

    if workers == 0:
        del content['spec']['tfReplicaSpecs']['Worker']
        worker_spec = None
    else:
        worker_spec = content['spec']['tfReplicaSpecs']['Worker']

    if pss == 0:
        del content['spec']['tfReplicaSpecs']['PS']
        ps_spec = None
    else:
        ps_spec = content['spec']['tfReplicaSpecs']['PS']

    wandb_env = [{"WANDB_API_KEY": os.getenv("WANDB_API_KEY")}]

    master_spec = content['spec']['tfReplicaSpecs']['MASTER']
    master_spec['template']['spec']['containers'][0]['image'] = trainer_image
    if gpus != 0:
        master_spec['template']['spec']['containers'][0]['resources']['requests']['nvidia.com/gpu'] = gpus
    if worker_spec:
        worker_spec['template']['spec']['containers'][0]['image'] = trainer_image
        worker_spec['template']['spec']['containers'][0]['command'] = command
    if ps_spec:
        ps_spec['template']['spec']['containers'][0]['image'] = trainer_image
        ps_spec['template']['spec']['containers'][0]['command'] = command

    return content


def _upload_wandb_webapp(gcs_path, wandb_project, job_name):
    # TODO: Check if we're local and change the url
    # We can use this once my pull is approved
    # client = Minio('minio-service.kubeflow:9000',
    #               access_key='minio',
    #               secret_key='minio123',
    #               secure=False)
    #client.fput_object('mlpipeline', wbpath, "wandb.html")
    wandb_path = os.path.join("artifacts", job_name, "wandb.html")
    output_path = os.path.join(gcs_path, wandb_path)
    _, _, bucket, key = output_path.split("/", 3)
    blob = storage.Client().get_bucket(bucket).blob(key)
    run_path = os.path.join(wandb_project, job_name)

    template = os.path.join(os.path.dirname(
        os.path.realpath(__file__)), "wandb.template.html")
    blob.upload_from_string(
        open(template).read().replace("$RUN_PATH", run_path))
    return output_path, run_path


def launch_tfjob(command, workers=0, pss=0, gpus=0, kf_version='v1alpha2', tfjob_ns='default',
                 tfjob_timeout_minutes=10, container_image="gcr.io/ml-pipeline/ml-pipeline-kubeflow-tf-trainer:0.1.3-rc.2",
                 output_dir=None, wandb_project=None, ui_metadata_type="tensorboard"):
    """Launch a TFJob and wait for it to complete"""
    try:
        from minio import Minio
        from google.cloud import storage
        from kubernetes import client as k8s_client
        from kubernetes import config
    except ImportError:
        wandb.termerror(
            "Required libraries for kubeflow aren't installed, run `pip install wandb[kubeflow]`")

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    root = logging.getLogger()
    logging.setLevel(logging.INFO)
    root.addHandler(logging.StreamHandler(sys.stdout))
    logging.info('Generating training template.')
    template_file = os.path.join(os.path.dirname(
        os.path.realpath(__file__)), 'train.template.yaml')
    content_yaml = _generate_train_yaml(
        template_file, tfjob_ns, workers, pss, container_image, command, gpus)

    logging.info('Starting training.')

    api_client = k8s_client.ApiClient()
    create_response = tf_job_client.create_tf_job(
        api_client, content_yaml, version=kf_version)
    job_name = create_response['metadata']['name']

    if output_dir and os.path.exists("/argo/podmetadata"):
        web_app_source, run_path = _upload_wandb_webapp(
            output_dir, wandb_project or "FAKE/PROJECT", job_name)

        metadata = {
            'outputs': [{
                'type': ui_metadata_type,
                'source': output_dir,
            }, {
                'type': 'web-app',
                'source': web_app_source
            }
            ]}
        with open('/mlpipeline-ui-metadata.json', 'w') as f:
            json.dump(metadata, f)
        logging.info('Run configured with W&B, view live results here: {}'.format(
            "https://app.wandb.ai/"+run_path))

    wait_response = tf_job_client.wait_for_job(
        api_client, tfjob_ns, job_name, kf_version,
        timeout=datetime.timedelta(minutes=tfjob_timeout_minutes))
    succ = True
    # TODO: update this failure checking after tf-operator has the condition checking function.
    if 'Worker' in wait_response['status']['tfReplicaStatuses']:
        if 'Failed' in wait_response['status']['tfReplicaStatuses']['Worker']:
            logging.error('Training failed since workers failed.')
            succ = False
    if 'PS' in wait_response['status']['tfReplicaStatuses']:
        if 'Failed' in wait_response['status']['tfReplicaStatuses']['PS']:
            logging.error('Training failed since PSs failed.')
            succ = False
    if 'MASTER' in wait_response['status']['tfReplicaStatuses']:
        if 'Failed' in wait_response['status']['tfReplicaStatuses']['MASTER']:
            logging.error('Training failed since MASTER failed.')
            succ = False

    # TODO: remove this after kubeflow fixes the wait_for_job issue
    # because the wait_for_job returns when the worker finishes but the master might not be complete yet.
    if 'MASTER' in wait_response['status']['tfReplicaStatuses'] and 'active' in wait_response['status']['tfReplicaStatuses']['MASTER']:
        master_active = True
        while master_active:
            # Wait for master to finish
            time.sleep(2)
            wait_response = tf_job_client.wait_for_job(api_client, tfjob_ns, job_name, kf_version,
                                                       timeout=datetime.timedelta(minutes=tfjob_timeout_minutes))
            if 'active' not in wait_response['status']['tfReplicaStatuses']['MASTER']:
                master_active = False

    if succ:
        logging.info('Training success.')

    tf_job_client.delete_tf_job(
        api_client, tfjob_ns, job_name, version=kf_version)


def tfjob_launcher_op(container_image, command, wandb_project, number_of_workers,
                      number_of_parameter_servers, tfjob_timeout_minutes, output_dir=None,
                      step_name='W&B-TFJob-launcher'):
    from kfp import dsl
    op = dsl.ContainerOp(
        name=step_name,
        image='wandb/tfjob-launcher:latest',
        arguments=[
            '--workers', number_of_workers,
            '--pss', number_of_parameter_servers,
            '--tfjob-timeout-minutes', tfjob_timeout_minutes,
            '--container-image', container_image,
            '--wandb-project', wandb_project,
            '--output-dir', output_dir,
            '--ui-metadata-type', 'tensorboard',
            '--',
        ] + command,
        file_outputs={'train': '/output.txt'}
    )
    key = Api().api_key
    if key is None:
        raise ValueError("Not logged into W&B, run `wandb login`")
    op.add_env_variable({"WANDB_API_KEY": key})
    return op
