import logging
from threading import Lock, Thread
import urllib3
from dateutil import parser
from typing import Dict, List, Optional, Any

from kubernetes import watch
from kubernetes.client import (
    BatchV1Api,
    CoreV1Api,
    CustomObjectsApi,
    V1PodStatus,
    ApiException,
)

from wandb.sdk.launch.errors import LaunchError
from .abstract import Status, State

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

    def stream(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Stream the watcher."""
        while True:
            try:
                for event in self._watcher.stream(func, *args, **kwargs):
                    # Save the resource version so that we can resume the stream
                    # if it breaks.
                    kwargs["resource_version"] = event.get(
                        "object"
                    ).metadata.resource_version
                    yield event
            except urllib3.exceptions.ProtocolError as e:
                _logger.warning(f"Broken event stream: {e}")
            except ApiException as e:
                _logger.warning(f"Exception when calling {func}: {e}")
            except Exception as e:
                raise e

    def stop(self) -> None:
        """Stop the watcher."""
        self._watcher.stop()


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
    if len(conditions) > 0:
        # sort conditions by lastTransitionTime
        conditions.sort(
            key=lambda x: _parse_transition_time(x.get("lastTransitionTime", ""))
        )
        delta_condition = conditions[-1]
        if delta_condition.get("status") == "True":
            return delta_condition.get("type")
    return None


def _parse_transition_time(time_str: str) -> float:
    """Convert a string representing a time to a timestamp."""
    dt = parser.parse(time_str)
    return dt.timestamp()


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
        """Initial KubernetesRunMonitor.

        Arguments:
            jobname: Name of the job.

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

        self._watch_job_thread = Thread(target=self._watch_job, daemon=True)
        self._watch_pods_thread = Thread(target=self._watch_pods, daemon=True)
        self._watch_crd_thread = Thread(target=self._watch_crd, daemon=True)

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
            return self._status

    def _watch_pods(self) -> None:
        """Watch for pods created matching the jobname."""
        try:
            # Stream with no timeout polling for pod status updates
            for event in self._pod_watcher.stream(
                self.core_api.list_namespaced_pod,
                namespace=self.namespace,
                label_selector=self.pod_label_selector,
            ):
                type = event.get("type")
                object = event.get("object")

                if type == "MODIFIED":
                    if object.status.phase == "Running":
                        self._set_status(Status("running"))
                if _is_preempted(object.status):
                    self._set_status(Status("preempted"))
                    self.stop()
                    break
                if _is_container_creating(object.status):
                    self._set_status(Status("starting"))

        # This can happen if the initial cluster connection fails.
        except ApiException as e:
            raise LaunchError(
                f"Exception when calling CoreV1Api.list_namespaced_pod with selector {self.pod_label_selector}: {e}"
            )

        # # This can happen if the stream starts and gets broken, typically because
        # # a thread is hanging. The kubernetes SDK is already implementing a
        # # retry loop so if we get here it means that the pods cannot be monitored.
        # except urllib3.exceptions.ProtocolError as e:
        #     state = self.get_status().state
        #     if state in ["failed", "finished", "preempted"]:
        #         _logger.warning(
        #             f"Hanging pod monitor thread with selector {self.pod_label_selector}: {e}"
        #         )
        #         return
        #     raise LaunchError(
        #         f"Broken event stream for pod watcher in state '{state}' and selector {self.pod_label_selector}: {e}"
        #     )

    def _watch_job(self) -> None:
        """Watch for job matching the jobname."""
        try:
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

        # This can happen if the initial cluster connection fails.
        except ApiException as e:
            raise LaunchError(
                f"Exception when calling CoreV1Api.list_namespaced_job with selector {self.job_field_selector}: {e}"
            )

        # This can happen if the connection is lost to the Kubernetes API server
        # and cannot be re-established.
        except urllib3.exceptions.ProtocolError as e:
            state = self.get_status().state
            if state in ["finished", "failed"]:
                _logger.warning(
                    f"Hanging job monitor thread with select {self.job_field_selector}: {e}"
                )
                return
            raise LaunchError(
                f"Broken event stream for job watcher in state {state} with selector {self.job_field_selector}: {e}"
            )

    def _watch_crd(self) -> None:
        """Watch for CRD matching the jobname."""
        try:
            for event in self._job_watcher.stream(
                self.custom_api.list_namespaced_custom_object,
                namespace=self.namespace,
                field_selector=self.job_field_selector,
                group=self.group,
                version=self.version,
                plural=self.plural,
            ):
                event_type = event.get("type")
                # This check is needed because CRDs will often not have a status
                # on the ADDED event, and the status at that time is not useful
                # in any case.
                # TODO: Use a constant for these event types.
                if event_type == "MODIFIED":
                    object = event.get("object")
                    status = object.get("status")
                    state = status.get("state")
                    if isinstance(state, dict):
                        state = state.get("phase")
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
                            pass
                    if state is None:
                        continue
                    status = Status(CRD_STATE_DICT.get(state.lower(), "unknown"))
                    self._set_status(status)
                    if status.state in ["finished", "failed", "preempted"]:
                        self.stop()
                        break

        # Handle exceptions here.
        except Exception as e:
            raise e
