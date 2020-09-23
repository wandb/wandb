"""Agent tests"""
import pytest
import wandb


@pytest.mark.skip(reason="This test doesn't work yet")
def test_agent(live_mock_server, dummy_api_key):
    assert True

    def train():
        # Here we're in a different process. It's hard to communicate
        # back to the main process for assertions.

        settings = wandb.Settings(
            base_url="http://localhost",
            api_key=dummy_api_key)

        # TODO: Fix this.
        # There is an issue here, the agent sets the environment variable
        # WANDB_SWEEP_ID and wandb.init() should pick that up. But it doesn't,
        # I think because the settings object has been frozen at some other time.
        run = wandb.init(settings=settings)

        # If this assertion fails, the test will timeout (because we
        # never complete 1 agent run)
        assert run.sweep_id == 'test-sweep-id'
    wandb.agent('test-sweep-id', function=train, count=1)
