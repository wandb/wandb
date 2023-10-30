import unittest.mock

import wandb.sdk.verify.verify as wandb_verify
from wandb.apis import InternalApi


def test_check_logged_in(wandb_init):
    internal_api = unittest.mock.MagicMock(spec=InternalApi)
    internal_api.api_key = None
    assert not wandb_verify.check_logged_in(internal_api, "localhost:8000")

    run = wandb_init()
    assert wandb_verify.check_logged_in(InternalApi(), run.settings.base_url)
    run.finish()
