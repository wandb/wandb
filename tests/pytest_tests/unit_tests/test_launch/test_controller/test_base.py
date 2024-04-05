from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.agent2.controllers.base import BaseManager
from wandb.sdk.launch.agent2.jobset import JobSet
from wandb.sdk.launch.queue_driver.abstract import AbstractQueueDriver


class TestBaseManager(BaseManager):
    resource_type = "test"

    def __init__(self, config, jobset, logger, legacy, max_concurrency):
        self.queue_driver = MagicMock(spec=AbstractQueueDriver)
        super().__init__(config, jobset, logger, legacy, max_concurrency)


@pytest.fixture
def jobset():
    return MagicMock(spec=JobSet)


@pytest.fixture
def config():
    return {"jobset_spec": {"name": "test"}, "agent_id": "test"}


def test_reconcile_launch_item(jobset):
    mgr = TestBaseManager()


def test_reconcile_clear_unowned_item(jobset):
    mgr = TestBaseManager()


def test_reconcile_max_concurrency(jobset):
    mgr = TestBaseManager()


def test_construct_discoverability_label(jobset):
    mgr = TestBaseManager()


def test_get_resource_block():
    mgr = TestBaseManager()
    mgr.queue_driver.get_resource_block = MagicMock()
    mgr.get_resource_block()
    mgr.queue_driver.get_resource_block.assert_called_once()


def test_label_job():
    pass


def test_find_orphaned_jobs(self):
    pass
