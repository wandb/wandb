import datetime
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

if False:
    import kubernetes   # type: ignore
from six.moves import shlex_quote
import wandb
import wandb.docker as docker
from wandb.errors import LaunchError
from wandb.util import get_module, load_json_yaml_dict
import yaml

from .abstract import AbstractRun, AbstractRunner, Status
from .._project_spec import LaunchProject
from ..docker import (
    construct_local_image_uri,
    generate_docker_image,
    pull_docker_image,
    validate_docker_installation,
)
from ..utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)

TIMEOUT = 5

class KubernetesSubmittedRun(AbstractRun):
    from kubernetes.client.api.batch_v1_api import BatchV1Api

    def __init__(self, batch_api: BatchV1Api, name: str, namespace: Optional[str] = 'default') -> None:
        self.batch_api = batch_api
        self.name = name
        self.namespace = namespace
        self.job = self.batch_api.read_namespaced_job(name=self.name, namespace=self.namespace)

    @property
    def id(self) -> str:
        return self.name

    def wait(self) -> bool:
        while True:
            status = self.get_status()
            wandb.termlog("Job {} status: {}".format(self.name, status))
            if status != "running":
                break
            time.sleep(5)
        return status == "finished"     # todo: not sure if this (copied from aws runner) is the right approach? should we return false on failure

    def get_status(self) -> Status:
        job_response = self.batch_api.read_namespaced_job_status(name=self.name, namespace=self.namespace)
        status = job_response.status
        # todo: we only handle the 1 pod case. see https://kubernetes.io/docs/concepts/workloads/controllers/job/#parallel-jobs for multipod handling
        if status.succeeded == 1:
            return Status("finished")
        elif status.failed == 1:
            return Status("failed")
        elif status.active == 1:
            return Status("running")
        if status.conditions is not None and status.conditions[0].type == "Suspended":
            return Status("stopped")
        return Status("unknown")

    def suspend(self) -> None:
        self.job.spec.suspend = True
        self.batch_api.patch_namespaced_job(name=self.name, namespace=self.namespace, body=self.job)
        timeout = TIMEOUT
        job_response = self.batch_api.read_namespaced_job_status(name=self.name, namespace=self.namespace)
        while job_response.status.conditions is None and timeout > 0:
            time.sleep(1)
            timeout -= 1
            job_response = self.batch_api.read_namespaced_job_status(name=self.name, namespace=self.namespace)
        
        if timeout == 0 or job_response.status.conditions[0].type != "Suspended":
            raise LaunchError("Failed to suspend job {}. Check Kubernetes dashboard for more info.".format(self.name))

    def cancel(self) -> None:
        self.suspend()
        # todo: is that right? suspension will already delete all active pods but suspended jobs can be resumed/uncancelled - should we delete the job
        

class KubernetesRunner(AbstractRunner):
    def run(self, launch_project: LaunchProject) -> Optional[AbstractRun]:
        kubernetes = get_module("kubernetes", "KubernetesRunner requires kubernetes to be installed")

        resource_args = launch_project.resource_args.get("kubernetes")
        if resource_args is None:
            raise LaunchError("No Kubernetes resource args specified. Specify args via --resource-args with a JSON file or string under top-level key kubernetes")
        
        config_file = resource_args.get("config_file")   # kubeconfig, if None then loads default in ~/.kube
        if config_file is not None or os.path.exists("~/.kube/config"):
            kubernetes.config.load_kube_config(config_file)


        batch_api = kubernetes.client.BatchV1Api()
        core_api = kubernetes.client.CoreV1Api()
        api_client = kubernetes.client.ApiClient()

        # allow users to specify template or entire spec
        if resource_args.get("job_spec"):
            job_dict = load_json_yaml_dict(resource_args['job_spec'])
        else:
            # begin constructing job sped
            job_dict = {'apiVersion': 'batch/v1', 'kind': 'Job'}

        # extract job spec component parts for convenience
        job_metadata = job_dict.get("metadata", {})
        job_spec = job_dict.get("spec", {})
        pod_template = job_spec.get("template", {})
        pod_metadata = pod_template.get("metadata", {})
        pod_spec = pod_template.get("spec", {})
        containers = pod_spec.get("containers", [{}])
        job_status = job_dict.get('status', {})

        # begin pulling resource arg overrides. all of these are optional

        # allow top-level namespace override, otherwise take namespace specified at the job level, or default
        namespace = resource_args.get("namespace", job_metadata.get("namespace", "default"))

        # name precedence: resource args override > name in spec file > generated name
        job_metadata['name'] = resource_args.get("job_name", job_metadata.get('name'))
        if not job_metadata.get('name'):
            job_metadata['generateName'] = "launch-"

        if resource_args.get('cluster_name'):
            job_metadata['clusterName'] = resource_args.get("cluster_name")
        if resource_args.get('job_labels'):
            job_metadata['labels'] = resource_args.get('job_labels')

        if resource_args.get('backoff_limit'):
            job_spec['backoffLimit'] = resource_args.get('backoff_limit')
        if resource_args.get('job_completions'):
            job_spec['completions'] = resource_args.get('job_completions')
        if resource_args.get('parallelism'):
            job_spec['parallelism'] = resource_args.get('parallelism')
        if resource_args.get('suspend'):
            job_spec['suspend'] = resource_args.get('suspend')

        # only support container overrides for the single container case
        if any(arg in resource_args for arg in ['container_name', 'resource_requests', 'resource_limits']):
            raise LaunchError("Resource overrides not supported for multiple containers. Multiple container configurations should be specified in a yaml file supplied via job_spec.")

        containers[0]['name'] = resource_args.get("container_name", containers[0].get('name', 'launch'))
        container_resources = containers[0].get('resources', {})
        if resource_args.get('resource_requests'):
            container_resources['requests'] = resource_args.get("resource_requests")
        if resource_args.get('resource_limits'):
            container_resources['limits'] = resource_args.get('resource_limits')
        if container_resources:
            containers[0]['resources'] = container_resources
        # todo: args and env vars would be added here, need to figure out what kind of overrides we want

        pod_spec['restartPolicy'] = resource_args.get('pod_restart_policy', 'Never')
        if resource_args.get('pod_preemption_policy'):
            pod_spec['preemptionPolicy'] = resource_args.get("pod_preemption_policy")
        if resource_args.get('node_name'):
            pod_spec['nodeName'] = resource_args.get('node_name')
        if resource_args.get('node_selectors'):
            pod_spec['nodeSelectors'] = resource_args.get('node_selectors')

        validate_docker_installation()
        entry_point = launch_project.get_single_entry_point()
        docker_args: Dict[str, Any] = self.backend_config[PROJECT_DOCKER_ARGS]
        if docker_args and list(docker_args) != ['docker_image']:
            wandb.termwarn(
                "Docker args are not supported for Kubernetes. Not using docker args"
            )

        image = resource_args.get("image")
        if image:
            if launch_project.docker_image and image != launch_project.docker_image:
                raise LaunchError("Conflicting Docker images specified in launch and resource args.")
            if len(containers) > 1:
                raise LaunchError("Multiple container configurations should be specified in a yaml file supplied via job_spec.")
        user_provided_image = image or launch_project.docker_image
        if user_provided_image:
            pull_docker_image(user_provided_image)
            containers[0]['image'] = user_provided_image
        else:
            registry = resource_args.get("registry")
            if registry is None:
                # allow local registry usage for eg local clusters but throw a warning
                wandb.termlog("Warning: No Docker registry specified. Image will be hosted on local registry, which may not be accessible to your training cluster.")

            image_uri = construct_local_image_uri(launch_project)
            if registry:
                image_uri = os.path.join(registry, image_uri)
            generate_docker_image(self._api, launch_project, image_uri, entry_point, docker_args, runner_type="kubernetes")
            containers[0]['image'] = image_uri
            if registry:
                repo, tag = image_uri.split(':')
                docker.push(repo, tag)

        # reassemble spec
        pod_spec['containers'] = containers
        pod_template['spec'] = pod_spec
        pod_template['metadata'] = pod_metadata
        job_spec['template'] = pod_template
        job_dict['spec'] = job_spec
        job_dict['metadata'] = job_metadata
        job_dict['status'] = job_status

        job_response = kubernetes.utils.create_from_yaml(api_client, yaml_objects=[job_dict], namespace=namespace)[0][0]   # create_from_yaml returns a nested list of k8s objects
        job_name = job_response.metadata.labels['job-name']

        pods = core_api.list_namespaced_pod(label_selector="job-name={}".format(job_name), namespace=namespace)
        timeout = TIMEOUT
        while len(pods.items) == 0 and timeout > 0:
            time.sleep(1)
            timeout -= 1
            pods = core_api.list_namespaced_pod(label_selector="job-name={}".format(job_name), namespace=namespace)

        if timeout == 0:
            raise LaunchError("No pods found for job {}. Check dashboard to see if job was launched successfully.".format(job_name))

        pod_names = [pi.metadata.name for pi in pods.items]
        wandb.termlog("Job {job} created on pod(s) {pod}".format(job=job_name, pod=', '.join(pod_names)))

        submitted_job = KubernetesSubmittedRun(batch_api, job_name, namespace)
        return submitted_job

