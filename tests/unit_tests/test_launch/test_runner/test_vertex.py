from unittest.mock import MagicMock

import pytest
from wandb.apis.internal import Api
from wandb.sdk.launch._project_spec import LaunchProject
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.runner.vertex_runner import VertexRunner, VertexSubmittedRun


class MockCustomJob:
    """Mock of the CustomJob class from the Vertex SDK.

    This is used to test the VertexSubmittedRun class which uses that object
    to poll on the status of the job.
    """

    def __init__(self, statuses: list[str]):
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


@pytest.mark.asyncio
async def test_vertex_submitted_run():
    """Test that the submitted run works as expected."""
    job = MockCustomJob(["PENDING", "RUNNING", "SUCCEEDED", "FAILED"])
    run = VertexSubmittedRun(job)
    link = run.get_page_link()
    assert (
        link
        == "https://console.cloud.google.com/vertex-ai/locations/test-location/training/test-name?project=test-project"
    )
    assert (await run.get_status()).state == "starting"
    assert (await run.get_status()).state == "running"
    assert (await run.get_status()).state == "finished"
    assert (await run.get_status()).state == "failed"


def launch_project_factory(resource_args: dict, api: Api):
    """Construct a dummy LaunchProject with the given resource args."""
    return LaunchProject(
        api=api,
        docker_config={
            "docker_image": "test-image",
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
    """Vertex runner initialized with no backend config."""
    registry = MagicMock()
    environment = MagicMock()

    async def _mock_get_credentials(*args, **kwargs):
        return MagicMock()

    async def _mock_verify(*args, **kwargs):
        return MagicMock()

    environment.get_credentials = _mock_get_credentials
    environment.verify = _mock_verify
    api = Api(default_settings=test_settings(), load_settings=False)
    runner = VertexRunner(api, {"SYNCHRONOUS": False}, environment, registry)
    return runner


@pytest.fixture
def mock_aiplatform(mocker):
    """Patch the aiplatform module with a mock object and return that object."""
    mock = MagicMock()

    def _fake_get_module(*args, **kwargs):
        return mock

    mocker.patch(
        "wandb.sdk.launch.runner.vertex_runner.get_module",
        side_effect=_fake_get_module,
    )
    return mock


@pytest.mark.asyncio
async def test_vertex_missing_worker_spec(vertex_runner):
    """Test that a launch error is raised when we are missing a worker spec."""
    resource_args = {"vertex": {"worker_pool_specs": []}}
    launch_project = launch_project_factory(resource_args, vertex_runner._api)
    with pytest.raises(LaunchError) as e:
        await vertex_runner.run(launch_project, "test-image")
    assert "requires at least one worker pool spec" in str(e.value)


@pytest.mark.asyncio
async def test_vertex_missing_staging_bucket(vertex_runner):
    """Test that a launch error is raised when we are missing a staging bucket."""
    resource_args = {
        "vertex": {
            "spec": {
                "worker_pool_specs": [
                    {
                        "machine_spec": {"machine_type": "n1-standard-4"},
                        "replica_count": 1,
                        "container_spec": {"image_uri": "test-image"},
                    }
                ]
            }
        }
    }
    launch_project = launch_project_factory(resource_args, vertex_runner._api)
    with pytest.raises(LaunchError) as e:
        await vertex_runner.run(launch_project, "test-image")
    assert "requires a staging bucket" in str(e.value)


@pytest.mark.asyncio
async def test_vertex_missing_image(vertex_runner):
    """Test that a launch error is raised when we are missing an image."""
    resource_args = {
        "vertex": {
            "spec": {
                "worker_pool_specs": [
                    {
                        "machine_spec": {"machine_type": "n1-standard-4"},
                        "replica_count": 1,
                    },
                    {
                        "machine_spec": {"machine_type": "n1-standard-4"},
                        "replica_count": 1,
                        "container_spec": {"image_uri": "test-image"},
                    },
                ],
                "stage_bucket": "test-bucket",
            }
        }
    }
    launch_project = launch_project_factory(resource_args, vertex_runner._api)
    with pytest.raises(LaunchError) as e:
        await vertex_runner.run(launch_project, "test-image")
    assert "requires a container spec" in str(e.value)


@pytest.mark.asyncio
async def test_vertex_runner_works(vertex_runner, mock_aiplatform):
    """Test that the vertex runner works as expected with good inputs."""
    resource_args = {
        "vertex": {
            "spec": {
                "worker_pool_specs": [
                    {
                        "machine_spec": {"machine_type": "n1-standard-4"},
                        "replica_count": 2,
                        "container_spec": {"image_uri": "test-image"},
                    },
                    {
                        "machine_spec": {"machine_type": "n1-standard-8"},
                        "replica_count": 1,
                        "container_spec": {"image_uri": "${image_uri}"},
                    },
                ],
                "staging_bucket": "test-bucket",
            }
        }
    }
    launch_project = launch_project_factory(resource_args, vertex_runner._api)
    submitted_run = await vertex_runner.run(launch_project, "test-image")
    mock_aiplatform.init()
    mock_aiplatform.CustomJob.assert_called_once()
    submitted_spec = mock_aiplatform.CustomJob.call_args[1]["worker_pool_specs"]
    assert len(submitted_spec) == 2
    assert submitted_spec[0]["machine_spec"]["machine_type"] == "n1-standard-4"
    assert submitted_spec[0]["replica_count"] == 2
    assert submitted_spec[0]["container_spec"]["image_uri"] == "test-image"
    assert submitted_spec[1]["machine_spec"]["machine_type"] == "n1-standard-8"
    assert submitted_spec[1]["replica_count"] == 1
    # This assertion tests macro substitution of the image uri.
    assert submitted_spec[1]["container_spec"]["image_uri"] == "test-image"

    submitted_run._job = MockCustomJob(["PENDING", "RUNNING", "SUCCEEDED"])
    assert (await submitted_run.get_status()).state == "starting"
    assert (await submitted_run.get_status()).state == "running"
    assert (await submitted_run.get_status()).state == "finished"
