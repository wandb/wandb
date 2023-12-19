from unittest import mock

import pytest
import wandb


def test_sentry_user_process(wandb_init):
    with mock.patch(
        "wandb.env.error_reporting_enabled",
        return_value=True,
    ), mock.patch("wandb._sentry") as mock_sentry:
        exception = Exception("injected")
        with mock.patch(
            "wandb.sdk.wandb_init._WandbInit.init",
            mock.Mock(side_effect=exception),
        ):
            mock_sentry.exception.return_value = None
            with pytest.raises(wandb.Error):
                _ = wandb_init()
            mock_sentry.exception.assert_called_with(exception)


def test_sentry_session(wandb_init):
    with mock.patch(
        "wandb.env.error_reporting_enabled",
        return_value=True,
    ), mock.patch("wandb._sentry") as mock_sentry:
        run = wandb_init()
        run.finish()
        assert sorted(
            [
                call[1]["process_context"]
                for call in mock_sentry.configure_scope.call_args_list
            ]
        ) == sorted(["service", "user", "user"])
        assert mock_sentry.end_session.called_once()
