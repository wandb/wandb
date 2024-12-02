"""Monitors kubernetes resources managed by the launch agent."""

import asyncio
import logging
import traceback
from typing import Any, Dict, List, Optional, Tuple, Union

import kubernetes_asyncio  # type: ignore # noqa: F401
import urllib3
from kubernetes_asyncio import watch
from kubernetes_asyncio.client import (  # type: ignore  # noqa: F401
    ApiException,
    BatchV1Api,
    CoreV1Api,
    CustomObjectsApi,
    V1Pod,
    V1PodStatus,
)

import wandb
from wandb.sdk.launch.agent import LaunchAgent
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.runner.abstract import State, Status
from wandb.sdk.launch.utils import get_kube_context_and_api_client

WANDB_K8S_LABEL_NAMESPACE = "wandb.ai"
WANDB_K8S_RUN_ID = f"{WANDB_K8S_LABEL_NAMESPACE}/run-id"
WANDB_K8S_LABEL_AGENT = f"{WANDB_K8S_LABEL_NAMESPACE}/agent"
WANDB_K8S_LABEL_MONITOR = f"{WANDB_K8S_LABEL_NAMESPACE}/monitor"


class Resources:
    JOBS = "jobs"
    PODS = "pods"


class CustomResource:
    """Class for custom resources."""

    def __init__(self, group: str, version: str, plural: str) -> None:
        """Initialize the CustomResource."""
        self.group = group
        self.version = version
        self.plural = plural

    def __str__(self) -> str:
        """Return a string representation of the CustomResource."""
        return f"{self.group}/{self.version}/{self.plural}"

    def __hash__(self) -> int:
        """Return a hash of the CustomResource."""
        return hash(str(self))


# Maps phases and conditions of custom objects to agent's internal run states.
CRD_STATE_DICT: Dict[str, State] = {
    "created": "starting",
    "pending": "starting",
    "running": "running",
    "completing": "running",
    "succeeded": "finished",
    "completed": "finished",
    "failed": "failed",
    "aborted": "failed",
    "timeout": "failed",
    "terminated": "failed",
    "terminating": "stopping",
}

_logger = logging.getLogger(__name__)


def create_named_task(name: str, coro: Any, *args: Any, **kwargs: Any) -> asyncio.Task:
    """Create a named task."""
    task = asyncio.create_task(coro(*args, **kwargs))
    task.set_name(name)
    task.add_done_callback(_log_err_task_callback)
    return task


def _log_err_task_callback(task: asyncio.Task) -> None:
    """Callback to log exceptions from tasks."""
    exec = task.exception()
    if exec is not None:
        if isinstance(exec, asyncio.CancelledError):
            wandb.termlog(f"Task {task.get_name()} was cancelled")
            return
        name = task.get_name()
        wandb.termerror(f"Exception in task {name}")
        tb = exec.__traceback__
        tb_str = "".join(traceback.format_tb(tb))
        wandb.termerror(tb_str)


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


def _is_pod_unschedulable(status: "V1PodStatus") -> Tuple[bool, str]:
    """Return whether the pod is unschedulable along with the reason message."""
    if not status.conditions:
        return False, ""
    for condition in status.conditions:
        if (
            condition.type == "PodScheduled"
            and condition.status == "False"
            and condition.reason == "Unschedulable"
        ):
            return True, condition.message
    return False, ""


def _get_crd_job_name(object: "V1Pod") -> Optional[str]:
    refs = object.metadata.owner_references
    if refs:
        return refs[0].name
    return None


def _state_from_conditions(conditions: List[Dict[str, Any]]) -> Optional[State]:
    """Get the status from the pod conditions."""
    true_conditions = [
        c.get("type", "").lower() for c in conditions if c.get("status") == "True"
    ]
    detected_states = {
        CRD_STATE_DICT[c] for c in true_conditions if c in CRD_STATE_DICT
    }
    # The list below is ordered so that returning the first state detected
    # will accurately reflect the state of the job.
    states_in_order: List[State] = [
        "finished",
        "failed",
        "stopping",
        "running",
        "starting",
    ]
    for state in states_in_order:
        if state in detected_states:
            return state
    return None


def _state_from_replicated_status(status_dict: Dict[str, int]) -> Optional[State]:
    """Infer overall job status from replicated job status for jobsets.

    More info on jobset:
    https://github.com/kubernetes-sigs/jobset/blob/main/docs/concepts/README.md

    This is useful for detecting when jobsets are starting.
    """
    pods_ready = status_dict.get("ready", 0)
    pods_active = status_dict.get("active", 0)
    if pods_ready >= 1:
        return "running"
    elif pods_active >= 1:
        return "starting"
    return None


class LaunchKubernetesMonitor:
    """Monitors kubernetes resources managed by the launch agent.

    Note: this class is forced to be a singleton in order to prevent multiple
    threads from being created that monitor the same kubernetes resources.
    """

    _instance = None  # This is used to ensure only one instance is created.

    def __new__(cls, *args: Any, **kwargs: Any) -> "LaunchKubernetesMonitor":
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
        label_selector: str,
    ):
        """Initialize the LaunchKubernetesMonitor."""
        self._core_api: CoreV1Api = core_api
        self._batch_api: BatchV1Api = batch_api
        self._custom_api: CustomObjectsApi = custom_api

        self._label_selector: str = label_selector

        # Dict mapping a tuple of (namespace, resource_type) to an
        # asyncio.Task that is monitoring that resource type in that namespace.
        self._monitor_tasks: Dict[
            Tuple[str, Union[str, CustomResource]], asyncio.Task
        ] = dict()

        # Map from job name to job state.
        self._job_states: Dict[str, Status] = dict()

    @classmethod
    async def ensure_initialized(
        cls,
    ) -> None:
        """Initialize the LaunchKubernetesMonitor."""
        if cls._instance is None:
            _, api_client = await get_kube_context_and_api_client(
                kubernetes_asyncio, {}
            )
            core_api = CoreV1Api(api_client)
            batch_api = BatchV1Api(api_client)
            custom_api = CustomObjectsApi(api_client)
            label_selector = f"{WANDB_K8S_LABEL_MONITOR}=true"
            if LaunchAgent.initialized():
                label_selector += f",{WANDB_K8S_LABEL_AGENT}={LaunchAgent.name()}"
            cls(
                core_api=core_api,
                batch_api=batch_api,
                custom_api=custom_api,
                label_selector=label_selector,
            )

    @classmethod
    def monitor_namespace(
        cls, namespace: str, custom_resource: Optional[CustomResource] = None
    ) -> None:
        """Start monitoring a namespaces for resources."""
        if cls._instance is None:
            raise LaunchError(
                "LaunchKubernetesMonitor not initialized, cannot monitor namespace."
            )
        cls._instance.__monitor_namespace(namespace, custom_resource=custom_resource)

    @classmethod
    def get_status(cls, job_name: str) -> Status:
        """Get the status of a job."""
        if cls._instance is None:
            raise LaunchError(
                "LaunchKubernetesMonitor not initialized, cannot get status."
            )
        return cls._instance.__get_status(job_name)

    @classmethod
    def status_count(cls) -> Dict[State, int]:
        """Get a dictionary mapping statuses to the # monitored jobs with each status."""
        if cls._instance is None:
            raise ValueError(
                "LaunchKubernetesMonitor not initialized, cannot get status counts."
            )
        return cls._instance.__status_count()

    def __monitor_namespace(
        self, namespace: str, custom_resource: Optional[CustomResource] = None
    ) -> None:
        """Start monitoring a namespaces for resources."""
        if (namespace, Resources.PODS) not in self._monitor_tasks:
            self._monitor_tasks[(namespace, Resources.PODS)] = create_named_task(
                f"monitor_pods_{namespace}",
                self._monitor_pods,
                namespace,
            )
        # If a custom resource is specified then we will start monitoring
        # that resource type in the namespace instead of jobs.
        if custom_resource is not None:
            if (namespace, custom_resource) not in self._monitor_tasks:
                self._monitor_tasks[(namespace, custom_resource)] = create_named_task(
                    f"monitor_{custom_resource}_{namespace}",
                    self._monitor_crd,
                    namespace,
                    custom_resource=custom_resource,
                )
        else:
            if (namespace, Resources.JOBS) not in self._monitor_tasks:
                self._monitor_tasks[(namespace, Resources.JOBS)] = create_named_task(
                    f"monitor_jobs_{namespace}",
                    self._monitor_jobs,
                    namespace,
                )

    def __get_status(self, job_name: str) -> Status:
        """Get the status of a job."""
        if job_name not in self._job_states:
            return Status("unknown")
        state = self._job_states[job_name]
        return state

    def __status_count(self) -> Dict[State, int]:
        """Get a dictionary mapping statuses to the # monitored jobs with each status."""
        counts = dict()
        for _, status in self._job_states.items():
            state = status.state
            if state not in counts:
                counts[state] = 1
            else:
                counts[state] += 1
        return counts

    def _set_status_state(self, job_name: str, state: State) -> None:
        """Set the status of the run."""
        if job_name not in self._job_states:
            self._job_states[job_name] = Status(state)
        elif self._job_states[job_name].state != state:
            self._job_states[job_name].state = state

    def _add_status_message(self, job_name: str, message: str) -> None:
        if job_name not in self._job_states:
            self._job_states[job_name] = Status("unknown")
        wandb.termwarn(f"Warning from Kubernetes for job {job_name}: {message}")
        self._job_states[job_name].messages.append(message)

    async def _monitor_pods(self, namespace: str) -> None:
        """Monitor a namespace for changes."""
        watcher = SafeWatch(watch.Watch())
        async for event in watcher.stream(
            self._core_api.list_namespaced_pod,
            namespace=namespace,
            label_selector=self._label_selector,
        ):
            obj = event.get("object")
            job_name = obj.metadata.labels.get("job-name") or _get_crd_job_name(obj)
            if job_name is None or not hasattr(obj, "status"):
                continue
            if self.__get_status(job_name) in ["finished", "failed"]:
                continue

            is_unschedulable, reason = _is_pod_unschedulable(obj.status)
            if is_unschedulable:
                self._add_status_message(job_name, reason)
            if obj.status.phase == "Running" or _is_container_creating(obj.status):
                self._set_status_state(job_name, "running")
            elif _is_preempted(obj.status):
                self._set_status_state(job_name, "preempted")

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
                self._set_status_state(job_name, "finished")
            elif obj.status.failed is not None and obj.status.failed >= 1:
                self._set_status_state(job_name, "failed")

            # If the job is deleted and we haven't seen a terminal state
            # then we will consider the job failed.
            if event.get("type") == "DELETED":
                if self._job_states.get(job_name) != Status("finished"):
                    self._set_status_state(job_name, "failed")

    async def _monitor_crd(
        self, namespace: str, custom_resource: CustomResource
    ) -> None:
        """Monitor a namespace for changes."""
        watcher = SafeWatch(watch.Watch())
        async for event in watcher.stream(
            self._custom_api.list_namespaced_custom_object,
            namespace=namespace,
            plural=custom_resource.plural,
            group=custom_resource.group,
            version=custom_resource.version,
            label_selector=self._label_selector,
        ):
            object = event.get("object")
            name = object.get("metadata", dict()).get("name")
            status = object.get("status")
            state = None
            if status is None:
                continue
            replicated_jobs_status = status.get("ReplicatedJobsStatus")
            if isinstance(replicated_jobs_status, dict):
                state = _state_from_replicated_status(replicated_jobs_status)
            state_dict = status.get("state")
            if isinstance(state_dict, dict):
                phase = state_dict.get("phase")
                if phase:
                    state = CRD_STATE_DICT.get(phase.lower())
            else:
                conditions = status.get("conditions")
                if isinstance(conditions, list):
                    state = _state_from_conditions(conditions)
                else:
                    # This should never happen.
                    _logger.warning(
                        f"Unexpected conditions type {type(conditions)} "
                        f"for CRD watcher in {namespace}"
                    )
            if state is None:
                continue
            self._set_status_state(name, state)


class SafeWatch:
    """Wrapper for the kubernetes watch class that can recover in more situations."""

    def __init__(self, watcher: watch.Watch) -> None:
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
                wandb.termwarn(f"Broken event stream: {e}, attempting to recover")
            except ApiException as e:
                if e.status == 410:
                    # If resource version is too old we need to start over.
                    del kwargs["resource_version"]
                    self._last_seen_resource_version = None
            except Exception as E:
                exc_type = type(E).__name__
                stack_trace = traceback.format_exc()
                wandb.termerror(
                    f"Unknown exception in event stream of type {exc_type}: {E}, attempting to recover. Stack trace: {stack_trace}"
                )
