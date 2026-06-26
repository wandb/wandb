"""Integration tests for the run_messages mechanism."""

import pytest
import wandb

from tests.fixtures.mock_wandb_log import MockWandbLog


@pytest.mark.usefixtures("user")  # test requires an online run
def test_prints_run_messages(mock_wandb_log: MockWandbLog):
    # This test may need to be rewritten if the message changes
    # or if the setting is updated.
    #
    # Any way to make wandb-core reliably print works here.
    settings = wandb.Settings(x_file_stream_max_line_bytes=10)

    with wandb.init(settings=settings) as run:
        run.log({"x": "too many bytes in this line"})

    mock_wandb_log.assert_warned(
        "Skipped uploading run.log() data that exceeded size limit",
    )
