import logging
from threading import Lock, Thread
from typing import Any, Dict, List, Optional

import urllib3
from kubernetes import watch  # type: ignore # noqa: F401
from kubernetes.client import (  # type: ignore # noqa: F401
    ApiException,
    BatchV1Api,
    CoreV1Api,
    CustomObjectsApi,
    V1PodStatus,
)

import wandb

from .abstract import State, Status

# Dict for mapping possible states of custom objects to the states we want to report
# to the agent.
CRD_STATE_DICT: Dict[str, State] = {
    # Starting states.
    "created": "starting",
    "pending": "starting",
    # Running states.
    "running": "running",
    "completing": "running",
    # Finished states.
    "succeeded": "finished",
    "completed": "finished",
    # Failed states.
    "failed": "failed",
    "aborted": "failed",
    "timeout": "failed",
    "terminated": "failed",
    # Stopping states.
    "terminating": "stopping",
}


_logger = logging.getLogger(__name__)


class SafeWatch:
    """Wrapper for the kubernetes watch class that can recover in more situations."""

    def __init__(self, watcher: "watch.Watch") -> None:
        """Initialize the SafeWatch."""
        self._watcher = watcher
        self._last_seen_resource_version: Optional[str] = None
        self._stopped = False

    def stream(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Stream the watcher."""
        while True:
            try:
                for event in self._watcher.stream(
                    func, *args, **kwargs, timeout_seconds=15
                ):
                    if self._stopped:
                        break
                    # Save the resource version so that we can resume the stream
                    # if it breaks.
                    object = event.get("object")
                    if isinstance(object, dict):
                        self._last_seen_resource_version = object.get(
                            "metadata", dict()
                        ).get("resourceVersion")
                    else:
                        self._last_seen_resource_version = (
                            object.metadata.resource_version
                        )
                    kwargs["resource_version"] = self._last_seen_resource_version
                    yield event
                # If stream ends after stop just break
                if self._stopped:
                    break
            except urllib3.exceptions.ProtocolError as e:
                wandb.termwarn(f"Broken event stream: {e}")
            except ApiException as e:
                if e.status == 410:
                    # If resource version is too old we need to start over.
                    del kwargs["resource_version"]
                    self._last_seen_resource_version = None
            except Exception as E:
                wandb.termerror(f"Unknown exception in event stream: {E}")

    def stop(self) -> None:
        """Stop the watcher."""
        self._watcher.stop()
        self._stopped = True


def _is_preempted(status: "V1PodStatus") -> bool:
    """Check if this pod has been preempted."""
    if hasattr(status, "conditions") and status.conditions is not None:
        for condition in status.conditions:
            if condition.type == "DisruptionTarget" and condition.reason in [
                "EvictionByEvictionAPI",
                "PreemptionByScheduler",
                "TerminationByKubelet",
            ]:
                return True
    return False


def _is_container_creating(status: "V1PodStatus") -> bool:
    """Check if this pod has started creating containers."""
    for container_status in status.container_statuses or []:
        if (
            container_status.state
            and container_status.state.waiting
            and container_status.state.waiting.reason == "ContainerCreating"
        ):
            return True
    return False


def _state_from_conditions(conditions: List[Dict[str, Any]]) -> Optional[str]:
    """Get the status from the pod conditions."""
    true_conditions = [
        c.get("type", "").lower() for c in conditions if c.get("status") == "True"
    ]
    detected_states = {
        CRD_STATE_DICT[c] for c in true_conditions if c in CRD_STATE_DICT
    }
    for state in ["finished", "failed", "stopping", "running", "starting"]:
        if state in detected_states:
            return state
    return None


class KubernetesRunMonitor:
    def __init__(
        self,
        job_field_selector: str,
        pod_label_selector: str,
        namespace: str,
        batch_api: "BatchV1Api",
        core_api: "CoreV1Api",
        custom_api: "CustomObjectsApi" = None,
        group: Optional[str] = None,
        version: Optional[str] = None,
        plural: Optional[str] = None,
    ) -> None:
        """Initialize KubernetesRunMonitor.

        If a custom api is provided, the group, version, and plural arguments must also
        be provided. These are used to query the custom api for a launched custom
        object (CRD). Group, version, and plural in this context refer to the
        Kubernetes API group, version, and plural for the CRD. For more information
        see: https://kubernetes.io/docs/tasks/access-kubernetes-api/custom-resources/custom-resource-definitions/

        The run monitor starts two threads to watch for pods and jobs/crds matching the
        provided selectors. The status is set to "starting" when the run monitor is
        initialized. The status is set to "running" when a pod matching the pod selector
        is found with a status of "Running" or has a container with a status of
        "ContainerCreating". The status is set to "finished" when a job matching the job
        selector is found with a status of "Succeeded". The status is set to "failed"
        when a job matching the job selector is found with a status of "Failed" or a pod
        matching the pod selector is found with a status of "Failed". The status is set
        to "preempted" when a pod matching the pod selector is found with a condition
        type of "DisruptionTarget" and a reason of "EvictionByEvictionAPI",
        "PreemptionByScheduler", or "TerminationByKubelet".

        The logic for the CRD is similar to the logic for the job, but we inspect
        both the phase of the CRD and the conditions since some CRDs do not have a
        phase field.

        Arguments:
            job_field_selector: The field selector for the job or crd.
            pod_label_selector: The label selector for the pods.
            namespace: The namespace to monitor.
            batch_api: The batch api client.
            core_api: The core api client.
            custom_api: The custom api client.
            group: The group of the CRD.
            version: The version of the CRD.
            plural: The plural of the CRD.

        Returns:
            None.
        """
        self.pod_label_selector = pod_label_selector
        self.job_field_selector = job_field_selector
        self.namespace = namespace
        self.batch_api = batch_api
        self.core_api = core_api
        self.custom_api = custom_api
        self.group = group
        self.version = version
        self.plural = plural

        self._status_lock = Lock()
        self._status = Status("starting")

        # Only one of the job or crd watchers will be used.
        self._watch_job_thread = Thread(target=self._watch_job, daemon=True)
        self._watch_crd_thread = Thread(target=self._watch_crd, daemon=True)

        self._watch_pods_thread = Thread(target=self._watch_pods, daemon=True)

        self._job_watcher = SafeWatch(watch.Watch())
        self._pod_watcher = SafeWatch(watch.Watch())

    def start(self) -> None:
        """Start the run monitor."""
        if self.custom_api is None:
            self._watch_job_thread.start()
        else:
            self._watch_crd_thread.start()
        self._watch_pods_thread.start()

    def stop(self) -> None:
        """Stop the run monitor."""
        self._job_watcher.stop()
        self._pod_watcher.stop()

    def _set_status(self, status: Status) -> None:
        """Set the run status."""
        with self._status_lock:
            self._status = status

    def get_status(self) -> Status:
        """Get the run status."""
        with self._status_lock:
            # Each time this is called we verify that our watchers are active.
            if self._status.state in ["running", "starting"]:
                if self.custom_api is None:
                    if not self._watch_job_thread.is_alive():
                        wandb.termwarn(
                            f"Job watcher thread is dead for {self.job_field_selector}"
                        )
                        self._watch_job_thread = Thread(
                            target=self._watch_job, daemon=True
                        )
                        self._watch_job_thread.start()
                else:
                    if not self._watch_crd_thread.is_alive():
                        wandb.termwarn(
                            f"CRD watcher thread is dead for {self.job_field_selector}"
                        )
                        self._watch_crd_thread = Thread(
                            target=self._watch_crd, daemon=True
                        )
                        self._watch_crd_thread.start()
                if not self._watch_pods_thread.is_alive():
                    wandb.termwarn(
                        f"Pod watcher thread is dead for {self.pod_label_selector}"
                    )
                    self._watch_pods_thread = Thread(
                        target=self._watch_pods, daemon=True
                    )
                    self._watch_pods_thread.start()
            return self._status

    def _watch_pods(self) -> None:
        """Watch for pods created matching the jobname."""
        # Stream with no timeout polling for pod status updates
        for event in self._pod_watcher.stream(
            self.core_api.list_namespaced_pod,
            namespace=self.namespace,
            label_selector=self.pod_label_selector,
        ):
            object = event.get("object")
            # Sometimes ADDED events will be missing field.
            if not hasattr(object, "status"):
                continue
            if object.status.phase == "Running":
                self._set_status(Status("running"))
            if _is_preempted(object.status):
                self._set_status(Status("preempted"))
                self.stop()
                break
            if _is_container_creating(object.status):
                self._set_status(Status("running"))

    def _watch_job(self) -> None:
        """Watch for job matching the jobname."""
        for event in self._job_watcher.stream(
            self.batch_api.list_namespaced_job,
            namespace=self.namespace,
            field_selector=self.job_field_selector,
        ):
            object = event.get("object")
            if object.status.succeeded == 1:
                self._set_status(Status("finished"))
                self.stop()
                break
            elif object.status.failed is not None and object.status.failed >= 1:
                self._set_status(Status("failed"))
                self.stop()
                break

    def _watch_crd(self) -> None:
        """Watch for CRD matching the jobname."""
        for event in self._job_watcher.stream(
            self.custom_api.list_namespaced_custom_object,
            namespace=self.namespace,
            field_selector=self.job_field_selector,
            group=self.group,
            version=self.version,
            plural=self.plural,
        ):
            object = event.get("object")
            status = object.get("status")
            if status is None:
                continue
            state = status.get("state")
            if isinstance(state, dict):
                raw_state = state.get("phase", "")
                state = CRD_STATE_DICT.get(raw_state)
            else:
                conditions = status.get("conditions")
                if isinstance(conditions, list):
                    state = _state_from_conditions(conditions)
                else:
                    # This should never happen.
                    _logger.warning(
                        f"Unexpected conditions type {type(conditions)} "
                        f"for CRD {self.job_field_selector}: {conditions}"
                    )
            if state is None:
                continue
            status = Status(state)
            self._set_status(status)
            if status.state in ["finished", "failed", "preempted"]:
                self.stop()
                break
