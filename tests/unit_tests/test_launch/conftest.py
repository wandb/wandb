import pytest
import wandb
from wandb.apis.internal import InternalApi
from wandb.sdk import wandb_setup


@pytest.fixture(autouse=True)
def launch_test_default_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    default_base_url = "https://api.wandb.ai"
    monkeypatch.setenv("WANDB_BASE_URL", default_base_url)
    wandb_setup.singleton().settings.base_url = default_base_url
    wandb.ensure_configured()


@pytest.fixture
def test_api(test_settings):
    return InternalApi(default_settings=test_settings(), load_settings=False)
