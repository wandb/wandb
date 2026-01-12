from __future__ import annotations

import pytest
from wandb.apis.internal import InternalApi


@pytest.fixture
def test_api(test_settings):
    return InternalApi(default_settings=test_settings(), load_settings=False)
