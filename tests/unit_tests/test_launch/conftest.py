import pytest
from wandb.sdk.internal.internal_api import Api as InternalApi


@pytest.fixture
def test_api(test_settings):
    return InternalApi(default_settings=test_settings(), load_settings=False)
