import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wandb.apis.internal import Api
from wandb.errors import CommError
from wandb.sdk.launch.agent.launch_api_provider import LaunchApiProvider
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.runner.abstract import AbstractRun


def _create_mock_api():
    """Create a mock API instance with common attributes."""
    api = MagicMock(spec=Api)
    api.api_url = "https://api.wandb.ai"
    return api


def _create_mock_run(api_key="job_api_key_123"):
    """Create a mock AbstractRun instance."""
    run = MagicMock(spec=AbstractRun)
    run.get_job_api_key = AsyncMock(return_value=api_key)
    run.cleanup_secrets = AsyncMock()
    return run


def _create_mock_job_tracker(entity="other_entity", run=None):
    """Create a mock JobAndRunStatusTracker instance."""
    tracker = MagicMock(spec=JobAndRunStatusTracker)
    tracker.entity = entity
    tracker.project = "test_project"
    tracker.run_id = "test_run_123"
    tracker.run_queue_item_id = "rqi_456"
    tracker.run = run
    return tracker


@pytest.fixture
def mock_agent_api():
    """Mock agent API instance."""
    return _create_mock_api()


@pytest.fixture
def launch_api_provider(mock_agent_api):
    """LaunchApiProvider instance for testing."""
    return LaunchApiProvider(mock_agent_api, "agent_entity")


@pytest.mark.asyncio
async def test_get_api_returns_job_api(launch_api_provider, mock_agent_api):
    """When job has API key available, should always use job API instance."""
    mock_run = _create_mock_run()
    job_tracker = _create_mock_job_tracker(entity="agent_entity", run=mock_run)
    
    with patch('wandb.sdk.launch.agent.launch_api_provider.Api') as MockApi:
        mock_job_api = MagicMock()
        MockApi.return_value = mock_job_api
        
        api = await launch_api_provider.get_api(job_tracker)
        
        # Should use job API even for same entity (for permission isolation)
        assert api is mock_job_api
        assert api is not mock_agent_api
        MockApi.assert_called_once_with(
            api_key="job_api_key_123",
            default_settings={"base_url": "https://api.wandb.ai"}
        )

@pytest.mark.asyncio
async def test_get_api_no_job_key_returns_agent_api(launch_api_provider, mock_agent_api):
    """When no job API key available, should fallback to agent API."""
    mock_run = _create_mock_run(api_key=None)
    job_tracker = _create_mock_job_tracker(run=mock_run)
    
    api = await launch_api_provider.get_api(job_tracker)
    assert api is mock_agent_api



@pytest.mark.asyncio
async def test_api_cache_works(launch_api_provider):
    """Should cache and reuse API instances for same API key."""
    mock_run = _create_mock_run()
    job_tracker = _create_mock_job_tracker(run=mock_run)
    
    with patch('wandb.sdk.launch.agent.launch_api_provider.Api') as MockApi:
        mock_job_api = MagicMock()
        MockApi.return_value = mock_job_api

        api1 = await launch_api_provider.get_api(job_tracker)
        api2 = await launch_api_provider.get_api(job_tracker)
        
        assert api1 is api2 is mock_job_api

        MockApi.assert_called_once()


@pytest.mark.asyncio
async def test_api_caching_different_keys(launch_api_provider):
    """Should create separate API instances for different run IDs."""
    mock_run1 = _create_mock_run()
    mock_run2 = _create_mock_run()
    
    job_tracker1 = _create_mock_job_tracker(run=mock_run1)
    job_tracker1.run_id = "run1"
    job_tracker2 = _create_mock_job_tracker(run=mock_run2) 
    job_tracker2.run_id = "run2"
    
    with patch('wandb.sdk.launch.agent.launch_api_provider.Api') as MockApi:
        mock_job_api1 = MagicMock()
        mock_job_api2 = MagicMock()
        MockApi.side_effect = [mock_job_api1, mock_job_api2]

        mock_run1.get_job_api_key.return_value = "key1"
        api1 = await launch_api_provider.get_api(job_tracker1)
        
        mock_run2.get_job_api_key.return_value = "key2"
        api2 = await launch_api_provider.get_api(job_tracker2)

        assert api1 is mock_job_api1
        assert api2 is mock_job_api2
        assert MockApi.call_count == 2

@pytest.mark.asyncio
async def test_remove_job_api_from_cache(launch_api_provider):
    """Should remove specific job API from cache."""
    mock_run = _create_mock_run()
    job_tracker = _create_mock_job_tracker(run=mock_run)
    
    launch_api_provider._job_api_cache["test_run_123"] = MagicMock()  # Cache by run ID
    launch_api_provider._job_api_cache["other_run"] = MagicMock()
    assert len(launch_api_provider._job_api_cache) == 2
    
    await launch_api_provider.remove_job_api_from_cache(job_tracker)
    
    # Should remove only the specific run ID
    assert "test_run_123" not in launch_api_provider._job_api_cache
    assert "other_run" in launch_api_provider._job_api_cache
    assert len(launch_api_provider._job_api_cache) == 1


@pytest.mark.parametrize(
    "exception_source",
    [
        "get_job_api_key",  # Exception from get_job_api_key
        "api_creation",     # Exception from API creation
    ]
)
@pytest.mark.asyncio
async def test_error_handling_fallback_to_agent_api(launch_api_provider, mock_agent_api, exception_source):
    """Should fallback to agent API when exceptions occur."""
    mock_run = _create_mock_run()
    job_tracker = _create_mock_job_tracker(run=mock_run)
    
    if exception_source == "get_job_api_key":
        mock_run.get_job_api_key.side_effect = Exception("API key fetch failed")
        api = await launch_api_provider.get_api(job_tracker)
    else:  # api_creation
        with patch('wandb.sdk.launch.agent.launch_api_provider.Api') as MockApi:
            MockApi.side_effect = Exception("API creation failed")
            api = await launch_api_provider.get_api(job_tracker)
    
    assert api is mock_agent_api
