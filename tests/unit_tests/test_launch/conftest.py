import sys

import pytest
from wandb.apis.internal import InternalApi

if sys.version_info < (3, 9):
    pytest.skip(
        "Launch is not supported on Python versions < 3.9", allow_module_level=True
    )


@pytest.fixture
def test_api(test_settings):
    return InternalApi(default_settings=test_settings(), load_settings=False)
