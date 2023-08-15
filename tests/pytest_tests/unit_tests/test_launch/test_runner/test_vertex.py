import pytest
from typing import List

from unittest.mock import MagicMock

from wandb.apis import InternalApi

from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.runner.vertex_runner import (
    VertexRunner,
    VertexSubmittedRun,
    GCP_CONSOLE_URI,
)


class MockCustomJob:
    """Mock of the CustomJob class from the Vertex SDK.

    This is used to test the VertexSubmittedRun class which uses that object
    to poll on the status of the job.
    """

    def __init__(self, statuses: List[str]):
        self.statuses = statuses
        self.status_index = 0

    @property
    def state(self):
        status = self.statuses[self.status_index]
        self.status_index += 1
        return f"JobState.JOB_STATE_{status}"

    @property
    def display_name(self):
        return "test-display-name"

    @property
    def location(self):
        return "test-location"

    @property
    def project(self):
        return "test-project"

    @property
    def name(self):
        return "test-name"

    @property
    def display_name(self):
        return "test-display-name"


def test_vertex_submitted_run():
    """Test that the submitted run works as expected."""
    job = MockCustomJob(["PENDING", "RUNNING", "SUCCEEDED", "FAILED"])
    run = VertexSubmittedRun(job)
    link = run.get_page_link()
    assert (
        link
        == "https://console.cloud.google.com/vertex-ai/locations/test-location/training/test-name?project=test-project"
    )
    assert run.get_status().state == "starting"
    assert run.get_status().state == "running"
    assert run.get_status().state == "finished"
    assert run.get_status().state == "failed"


def launch_project_factory(resource_args: dict, api: InternalApi):
    """Construct a dummy LaunchProject with the given resource args."""
    return LaunchProject(
        api=api,
        docker_config={
            "image": "test-image",
        },
        resource_args=resource_args,
        uri="",
        job="",
        launch_spec={},
        target_entity="",
        target_project="",
        name="",
        git_info={},
        overrides={},
        resource="vertex",
        run_id="",
    )


@pytest.fixture
def vertex_runner(test_settings):
    """Vertex runner initialized with no backend config"""
    registry = MagicMock()
    environment = MagicMock()
    api = InternalApi(settings=test_settings, load_settings=False)
    runner = VertexRunner(api, {"SYNCHRONOUS": False}, registry, environment)
    return runner


def test_vertex_missing_worker_spec(vertex_runner):
    """Test that a launch error is raised when we are missing a worker spec."""
    resource_args = {"vertex": {"worker_pool_specs": []}}
    launch_project = launch_project_factory(resource_args, vertex_runner._api)
    with pytest.raises(LaunchError):
        vertex_runner.run(launch_project, resource_args)


def test_vertex_missing_image(vertex_runner):
    """Test that a launch error is raised when we are missing an image."""
    resource_args = {
        "vertex": {
            "worker_pool_specs": [
                {
                    "machine_spec": {"machine_type": "n1-standard-4"},
                    "replica_count": 1,
                },
                {
                    "machine_spec": {"machine_type": "n1-standard-4"},
                    "replica_count": 1,
                    "image_uri": "test-image",
                },
            ]
        }
    }
    launch_project = launch_project_factory(resource_args, vertex_runner._api)
    with pytest.raises(LaunchError):
        vertex_runner.run(launch_project, resource_args)
