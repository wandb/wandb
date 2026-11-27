import unittest.mock

import wandb
import wandb.sdk.verify.verify as wandb_verify


def test_check_logged_in(user):
    api = unittest.mock.MagicMock(spec=wandb.Api)
    api.api_key = None
    assert not wandb_verify.check_logged_in(api, "localhost:8000")

    run = wandb.init()
    assert wandb_verify.check_logged_in(wandb.Api(), run.settings.base_url)
    run.finish()
