"""Monitors kubernetes resources managed by the launch agent."""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import urllib3
from kubernetes_asyncio import watch  # type: ignore # noqa: F401
from kubernetes_asyncio.client import (  # type: ignore # noqa: F401
    ApiException,
    BatchV1Api,
    CoreV1Api,
    CustomObjectsApi,
    V1PodStatus,
)

import wandb

from ..runner.abstract import State, Status


class Resources:
    JOBS = "jobs"
    PODS = "pods"


class JobState:
    FAILED = "failed"
    FINISHED = "finished"
    PENDING = "pending"
    PREEMPTED = "preempted"
    RUNNING = "running"
    STARTING = "starting"
    STOPPING = "stopping"

    # Dict for mapping possible states of custom objects to the states we want to report


# Maps phases and conditions of custom objects to agent's internal run states.
CRD_STATE_DICT: Dict[str, State] = {
    "created": JobState.STARTING,
    "pending": JobState.STARTING,
    "running": JobState.RUNNING,
    "completing": JobState.RUNNING,
    "succeeded": JobState.FINISHED,
    "completed": JobState.FINISHED,
    "failed": JobState.FAILED,
    "aborted": JobState.FAILED,
    "timeout": JobState.FAILED,
    "terminated": JobState.FAILED,
    "terminating": JobState.STOPPING,
}

_logger = logging.getLogger(__name__)


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
    # The list below is ordered so that returning the first state detected
    # will accurately reflect the state of the job.
    for state in [
        JobState.FINISHED,
        JobState.FAILED,
        JobState.STOPPING,
        JobState.RUNNING,
        JobState.STARTING,
    ]:
        if state in detected_states:
            return state
    return None


class LaunchKubernetesMonitor:
    """Monitors kubernetes resources managed by the launch agent.

    Note: this class is forced to be a singleton in order to prevent multiple
    threads from being created that monitor the same kubernetes resources.
    """

    _instance = None  # This is used to ensure only one instance is created.

    def __new__(cls, *args, **kwargs):
        """Create a new instance of the LaunchKubernetesMonitor.

        This method ensures that only one instance of the LaunchKubernetesMonitor
        is created. This is done to prevent multiple threads from being created
        that monitor the same kubernetes resources.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        core_api: CoreV1Api,
        batch_api: BatchV1Api,
        custom_api: CustomObjectsApi,
        label_selector: str = "app=wandb",
    ):
        """Initialize the LaunchKubernetesMonitor."""
        self._core_api: CoreV1Api = core_api
        self._batch_api: BatchV1Api = batch_api
        self._custom_api: CustomObjectsApi = custom_api
        self._label_selector = label_selector

        # Dict mapping a tuple of (namespace, resource_type) to an
        # asyncio.Task that is monitoring that resource type in that namespace.
        self._monitor_tasks: Dict[tuple(str), asyncio.Task] = dict()

        # Map from job name to job state.
        self._job_states: Dict[str, Status] = dict()

    @classmethod
    def initialize(cls, *args, **kwargs) -> None:
        """Initialize the LaunchKubernetesMonitor."""
        if cls._instance is None:
            cls._instance = cls(*args, **kwargs)
        else:
            raise ValueError(
                "LaunchKubernetesMonitor has already been initialized. "
                "It cannot be initialized more than once."
            )

    @classmethod
    def monitor_namespace(cls, namespace: str, custom_resource=None) -> None:
        """Start monitoring a namespaces for resources."""
        cls._check_initialized()
        cls._instance.__monitor_namespace(namespace, custom_resource=custom_resource)

    @classmethod
    def get_status(cls, job_name: str) -> Status:
        """Get the status of a job."""
        cls._check_initialized()
        return cls._instance.__get_status(job_name)

    @classmethod
    def status_count(cls) -> Dict[str, int]:
        """Get a dictionary mapping statuses to the # monitored jobs with each status."""
        cls._check_initialized()
        return cls._instance.__status_count()

    @classmethod
    def _check_initialized(cls) -> None:
        """Check if the LaunchKubernetesMonitor has been initialized."""
        if cls._instance is None:
            raise ValueError(
                "LaunchKubernetesMonitor must be initialized before it can be used."
            )

    def __monitor_namespace(self, namespace: str, custom_resource=None) -> None:
        """Start monitoring a namespaces for resources."""
        if (namespace, Resources.PODS) not in self._monitor_tasks:
            self._monitor_tasks[(namespace, Resources.PODS)] = asyncio.create_task(
                self._monitor_pods(namespace),
                name=f"monitor_{Resources.PODS}_{namespace}",
            )
        # If a custom resource is specified then we will start monitoring
        # that resource type in the namespace instead of jobs.
        if custom_resource is not None:
            if (namespace, custom_resource) not in self._monitor_tasks:
                self._monitor_tasks[(namespace, custom_resource)] = asyncio.create_task(
                    self._monitor_crd(namespace, custom_resource),
                    name=f"monitor_{custom_resource}_{namespace}",
                )
        else:
            if (namespace, Resources.JOBS) not in self._monitor_tasks:
                self._monitor_tasks[(namespace, Resources.JOBS)] = asyncio.create_task(
                    self._monitor_jobs(namespace),
                    name=f"monitor_{Resources.JOBS}_{namespace}",
                )

    def __get_status(self, job_name: str) -> Status:
        """Get the status of a job."""
        if job_name not in self._job_states:
            return Status(JobState.PENDING)
        state = self._job_states[job_name]
        return Status(state)

    def __status_count(self) -> Dict[str, int]:
        """Get a dictionary mapping statuses to the # monitored jobs with each status."""
        counts = dict()
        for _, state in self._job_states.items():
            if state not in counts:
                counts[state] = 1
            else:
                counts[state] += 1
        return counts

    def _set_status(self, job_name: str, status: Status) -> None:
        """Set the status of the run."""
        if self._job_states.get(job_name) != status:
            self._job_states[job_name] = status

    async def _monitor_pods(self, namespace: str) -> None:
        """Monitor a namespace for changes."""
        watcher = SafeWatch(watch.Watch())
        async for event in watcher.stream(
            self._core_api.list_namespaced_pod,
            namespace=namespace,
            label_selector=self._label_selector,
        ):
            obj = event.get("object")
            job_name = obj.metadata.labels.get("job-name")
            if job_name is None:
                continue
            # Sometimes ADDED events will be missing field.
            if not hasattr(obj, "status"):
                continue
            if obj.status.phase == "Running":
                self._set_status(job_name, Status(JobState.RUNNING))
            if _is_container_creating(obj.status):
                self._set_status(job_name, Status(JobState.RUNNING))
            if _is_preempted(obj.status):
                self._set_status(job_name, Status(JobState.PREEMPTED))

    async def _monitor_jobs(self, namespace: str) -> None:
        """Monitor a namespace for changes."""
        watcher = SafeWatch(watch.Watch())
        async for event in watcher.stream(
            self._batch_api.list_namespaced_job,
            namespace=namespace,
            label_selector=self._label_selector,
        ):
            obj = event.get("object")
            job_name = obj.metadata.name
            if obj.status.succeeded == 1:
                self._set_status(job_name, Status(JobState.FINISHED))
            elif obj.status.failed is not None and obj.status.failed >= 1:
                self._set_status(job_name, Status(JobState.FAILED))

    async def _monitor_crd(self, namespace: str, custom_resource: str) -> None:
        """Monitor a namespace for changes."""
        group = custom_resource.split("/")
        version = custom_resource.split("/")[1]
        kind = version
        plural = f"{kind.lower()}s"
        watcher = SafeWatch(watch.Watch())
        async for event in watcher.stream(
            namespace=namespace,
            plural=plural,
            group=group,
            version=version,
            kind=kind,
            label_selector=self._label_selector,
        ):
            object = event.get("object")
            name = object.get("metadata", dict()).get("name")
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
            self._set_status(name, status)
            if status.state in [JobState.FINISHED, JobState.FAILED, JobState.PREEMPTED]:
                self.stop()
                break


class SafeWatch:
    """Wrapper for the kubernetes watch class that can recover in more situations."""

    def __init__(self, watcher: "watch.Watch") -> None:
        """Initialize the SafeWatch."""
        self._watcher = watcher
        self._last_seen_resource_version: Optional[str] = None
        self._stopped = False

    async def stream(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Stream the watcher.

        This method will automatically resume the stream if it breaks. It will
        also save the resource version so that the stream can be resumed from
        the last seen resource version.
        """
        while True:
            try:
                async for event in self._watcher.stream(
                    func, *args, **kwargs, timeout_seconds=30
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
