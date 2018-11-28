"""Some utility functions for working with TFJobs.

Taken from: https://github.com/kubeflow/tf-operator/blob/master/py/tf_job_client.py
"""

import datetime
from six.moves import http_client
import json
import logging
import multiprocessing
import retrying
import time

from kubernetes import client as k8s_client
from kubernetes.client import rest

from wandb.kubeflow import k8s_util


TF_JOB_GROUP = "kubeflow.org"
TF_JOB_PLURAL = "tfjobs"
TF_JOB_KIND = "TFJob"

# How long to wait in seconds for requests to the ApiServer
TIMEOUT = 120


def create_tf_job(client, spec, version="v1beta1"):
    """Create a TFJob.
    Args:
      client: A K8s api client.
      spec: The spec for the job.
    """
    crd_api = k8s_client.CustomObjectsApi(client)
    try:
        # Create a Resource
        namespace = spec["metadata"].get("namespace", "default")
        thread = crd_api.create_namespaced_custom_object(
            TF_JOB_GROUP, version, namespace, TF_JOB_PLURAL, spec, async_req=True)
        api_response = thread.get(TIMEOUT)
        logging.info("Created job %s", api_response["metadata"]["name"])
        return api_response
    except rest.ApiException as e:
        message = ""
        if e.message:
            message = e.message
        if e.body:
            try:
                body = json.loads(e.body)
            except ValueError:
                # There was a problem parsing the body of the response as json.
                logging.error(
                    ("Exception when calling DefaultApi->"
                     "apis_fqdn_v1_namespaces_namespace_resource_post. body: %s"), e.body)
                raise
            message = body.get("message")

        logging.error(("Exception when calling DefaultApi->"
                       "apis_fqdn_v1_namespaces_namespace_resource_post: %s"),
                      message)
        raise e


def delete_tf_job(client, namespace, name, version="v1beta1"):
    crd_api = k8s_client.CustomObjectsApi(client)
    try:
        body = {
            # Set garbage collection so that job won't be deleted until all
            # owned references are deleted.
            "propagationPolicy": "Foreground",
        }
        logging.info("Deleting job %s.%s", namespace, name)
        thread = crd_api.delete_namespaced_custom_object(
            TF_JOB_GROUP, version, namespace, TF_JOB_PLURAL, name, body,
            async_req=True)
        api_response = thread.get(TIMEOUT)
        logging.info("Deleting job %s.%s returned: %s",
                     namespace, name, api_response)
        return api_response
    except rest.ApiException as e:
        message = ""
        if e.message:
            message = e.message
        if e.body:
            try:
                body = json.loads(e.body)
            except ValueError:
                # There was a problem parsing the body of the response as json.
                logging.error(
                    ("Exception when calling DefaultApi->"
                     "apis_fqdn_v1_namespaces_namespace_resource_post. body: %s"), e.body)
                raise
            message = body.get("message")

        logging.error(("Exception when calling DefaultApi->"
                       "apis_fqdn_v1_namespaces_namespace_resource_post: %s"),
                      message)
        raise e


@retrying.retry(wait_fixed=10000, stop_max_attempt_number=20)
def log_status(tf_job):
    """A callback to use with wait_for_job."""
    all_conditions = tf_job.get("status", {}).get("conditions", [])
    conditions = [] if all_conditions is None else [
        c.get("type", "") for c in all_conditions]
    logging.info("Job %s in namespace %s; uid=%s; conditions=%s",
                 tf_job.get("metadata", {}).get("name"),
                 tf_job.get("metadata", {}).get("namespace"),
                 tf_job.get("metadata", {}).get("uid"),
                 conditions)

# pylint: disable=too-many-arguments


def wait_for_condition(client,
                       namespace,
                       name,
                       expected_condition,
                       version="v1beta1",
                       timeout=datetime.timedelta(minutes=10),
                       polling_interval=datetime.timedelta(seconds=30),
                       status_callback=None):
    """Waits until any of the specified conditions occur.
    Args:
      client: K8s api client.
      namespace: namespace for the job.
      name: Name of the job.
      expected_condition: A list of conditions. Function waits until any of the
        supplied conditions is reached.
      timeout: How long to wait for the job.
      polling_interval: How often to poll for the status of the job.
      status_callback: (Optional): Callable. If supplied this callable is
        invoked after we poll the job. Callable takes a single argument which
        is the job.
    """
    crd_api = k8s_client.CustomObjectsApi(client)
    end_time = datetime.datetime.now() + timeout
    while True:
        # By setting async_req=True ApiClient returns multiprocessing.pool.AsyncResult
        # If we don't set async_req=True then it could potentially block forever.
        thread = crd_api.get_namespaced_custom_object(
            TF_JOB_GROUP, version, namespace, TF_JOB_PLURAL, name, async_req=True)

        # Try to get the result but timeout.
        results = None
        try:
            results = thread.get(TIMEOUT)
        except multiprocessing.TimeoutError:
            logging.error("Timeout trying to get TFJob.")
        except Exception as e:
            logging.error("There was a problem waiting for Job %s.%s; Exception; %s",
                          name, name, e)
            raise

        if results:
            if status_callback:
                status_callback(results)

            # If we poll the CRD quick enough status won't have been set yet.
            conditions = results.get("status", {}).get("conditions", [])
            # Conditions might have a value of None in status.
            conditions = conditions or []
            for c in conditions:
                if c.get("type", "") in expected_condition:
                    return results

        if datetime.datetime.now() + polling_interval > end_time:
            raise TimeoutError(
                "Timeout waiting for job {0} in namespace {1} to enter one of the "
                "conditions {2}.".format(
                    name, namespace, conditions))

        time.sleep(polling_interval.seconds)

    # Linter complains if we don't have a return statement even though
    # this code is unreachable.
    return None


def wait_for_job(client,
                 namespace,
                 name,
                 version="v1beta1",
                 timeout=datetime.timedelta(minutes=10),
                 polling_interval=datetime.timedelta(seconds=30),
                 status_callback=None):
    """Wait for the specified job to finish.
    Args:
      client: K8s api client.
      namespace: namespace for the job.
      name: Name of the job.
      timeout: How long to wait for the job.
      polling_interval: How often to poll for the status of the job.
      status_callback: (Optional): Callable. If supplied this callable is
        invoked after we poll the job. Callable takes a single argument which
        is the job.
    """
    return wait_for_condition(
        client, namespace, name, ["Succeeded", "Failed"],
        version=version,
        timeout=timeout,
        polling_interval=polling_interval,
        status_callback=status_callback)


def wait_for_delete(client,
                    namespace,
                    name,
                    version="v1beta1",
                    timeout=datetime.timedelta(minutes=5),
                    polling_interval=datetime.timedelta(seconds=30),
                    status_callback=None):
    """Wait for the specified job to be deleted.
    Args:
      client: K8s api client.
      namespace: namespace for the job.
      name: Name of the job.
      timeout: How long to wait for the job.
      polling_interval: How often to poll for the status of the job.
      status_callback: (Optional): Callable. If supplied this callable is
        invoked after we poll the job. Callable takes a single argument which
        is the job.
    """
    crd_api = k8s_client.CustomObjectsApi(client)
    end_time = datetime.datetime.now() + timeout
    while True:
        try:
            results = crd_api.get_namespaced_custom_object(
                TF_JOB_GROUP, version, namespace,
                TF_JOB_PLURAL, name)
        except rest.ApiException as e:
            if e.status == http_client.NOT_FOUND:
                return
            logging.exception("rest.ApiException thrown")
            raise
        if status_callback:
            status_callback(results)

        if datetime.datetime.now() + polling_interval > end_time:
            raise TimeoutError(
                "Timeout waiting for job {0} in namespace {1} to be deleted.".format(
                    name, namespace))

        time.sleep(polling_interval.seconds)


def get_labels(name, replica_type=None, replica_index=None):
    """Return labels.
    """
    labels = {
        "group_name": "kubeflow.org",
        "tf_job_name": name,
    }
    if replica_type:
        labels["tf-replica-type"] = replica_type

    if replica_index:
        labels["tf-replica-index"] = replica_index
    return labels


def to_selector(labels):
    parts = []
    for k, v in labels.iteritems():
        parts.append("{0}={1}".format(k, v))

    return ",".join(parts)


def wait_for_replica_type_in_phases(api_client, namespace, tfjob_name, replica_type, phases):
    pod_labels = get_labels(tfjob_name, replica_type)
    pod_selector = to_selector(pod_labels)
    k8s_util.wait_for_pods_to_be_in_phases(api_client, namespace,
                                           pod_selector,
                                           phases,
                                           timeout=datetime.timedelta(
                                               minutes=4))


@retrying.retry(wait_fixed=10, stop_max_delay=60)
def terminate_replica(master_host, namespace, target, exit_code=0):
    """Issue a request to terminate the requested TF replica running test_app.
    Args:
      master_host: The IP address of the master e.g. https://35.188.37.10
      namespace: The namespace
      target: The K8s service corresponding to the pod to terminate.
      exit_code: What exit code to terminate the pod with.
    """
    params = {
        "exitCode": exit_code,
    }
    util.send_request(master_host, namespace, target, "exit", params)


def terminate_replicas(api_client, namespace, name, replica, num_targets):
    """Terminates the specified replica(s).
    Args:
      api_client: K8s client
      namespace: K8s namespace
      name: TFJob name
      replica: Replica type (chief, worker, ps)
      num_targets: Number of replicas to terminate.
    """
    target = "{name}-{replica}".format(name=name, replica=replica)
    pod_labels = get_labels(namespace, name)
    pod_selector = to_selector(pod_labels)
    masterHost = api_client.configuration.host

    # Wait for the pods to be ready before we shutdown
    # TODO(jlewi): We are get pods using a label selector so there is
    # a risk that the pod we actual care about isn't present.
    logging.info("Waiting for pods to be running before shutting down.")
    k8s_util.wait_for_pods_to_be_in_phases(api_client, namespace,
                                           pod_selector,
                                           ["Running"],
                                           timeout=datetime.timedelta(
                                               minutes=4))
    logging.info("Pods are ready")
    logging.info("Issuing the terminate request")
    for num in range(num_targets):
        full_target = target + "-{0}".format(num)
        terminate_replica(masterHost, namespace, full_target)


def job_succeeded(tfjob):
    """Returns true if the TFJob succeeded; false otherwise.
    Args:
      tfjob: The TFJob custom resource returned from K8s.
    """
    last_condition = tfjob.get("status", {}).get("conditions", [])[-1]
    return last_condition.get("type", "").lower() == "succeeded"


def get_creation_failures_from_tfjob(api_client, namespace, tfjob):
    """Returns a list of pod/service creation failures, if any.
    Args:
      api_client: The K8s API client.
      namespace: The K8s namespace.
      tfjob: The TFJob custom resource returned from K8s.
    """
    uid = tfjob.get("metadata", {}).get("uid")
    events = k8s_util.get_events(api_client, namespace, uid)

    # Print out the K8s events because it can be useful for debugging.
    for e in events:
        logging.info("Received K8s Event:\n%s", e)

    created_pods, created_services = k8s_util.parse_events(events)

    num_expected = 0
    for replicakey in tfjob.get("spec", {}).get("tfReplicaSpecs", {}):
        replica_spec = tfjob.get("spec", {}).get(
            "tfReplicaSpecs", {}).get(replicakey, {})
        if replica_spec:
            num_expected += replica_spec.get("replicas", 1)

    creation_failures = []
    if len(created_pods) != num_expected:
        message = ("Expected {0} pods to be created but only "
                   "got {1} create events.").format(num_expected, len(created_pods))
        creation_failures.append(message)

    if len(created_services) != num_expected:
        message = ("Expected {0} services to be created but only "
                   "got {1} create events.").format(num_expected, len(created_services))
        creation_failures.append(message)

    return creation_failures
