import pytest
from wandb.sdk.launch.api import LaunchApi


@pytest.fixture
def test_api(patch_apikey, skip_verify_login):
    return LaunchApi()
