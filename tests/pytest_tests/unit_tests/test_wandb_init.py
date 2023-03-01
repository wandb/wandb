from unittest.mock import patch

import pytest
import wandb


def init():
    raise Exception("test")


def setup(_):
    pass


class MyExitError(Exception):
    pass


def os_exit(_):
    raise MyExitError("")


def test_init(test_settings):
    with patch("wandb.sdk.wandb_init._WandbInit", autospec=True) as mocked_wandbinit:
        with patch("wandb.sdk.wandb_init.logger", autospec=True), patch(
            "wandb.sdk.wandb_init.getcaller", autospec=True
        ), patch("os._exit", side_effect=os_exit), patch(
            "wandb.sdk.wandb_init.sentry_exc", autospec=True
        ), patch(
            "wandb._assert_is_user_process", side_effect=lambda: None
        ):
            instance = mocked_wandbinit.return_value
            instance.settings = test_settings(
                {"_except_exit": True, "problem": "fatal"}
            )
            instance.setup.side_effect = setup
            instance.init.side_effect = init
            with pytest.raises(MyExitError):
                wandb.init()
