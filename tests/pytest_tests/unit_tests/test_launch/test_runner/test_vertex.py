import pytest
from typing import List

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
