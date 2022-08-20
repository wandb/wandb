import time

import pytest


def end_run_basic(interface):
    time.sleep(1)


def end_run_pause_resume(interface):
    time.sleep(1)
    interface.publish_pause()
    time.sleep(1)
    interface.publish_resume()
    time.sleep(1)


def end_run_pause_pause(interface):
    time.sleep(1)
    interface.publish_pause()
    time.sleep(1)
    interface.publish_pause()
    time.sleep(1)


def end_run_resume_resume(interface):
    time.sleep(1)
    interface.publish_resume()
    time.sleep(1)
    interface.publish_resume()
    time.sleep(1)


def end_run_resume_pause(interface):
    time.sleep(1)
    interface.publish_resume()
    time.sleep(1)
    interface.publish_pause()
    time.sleep(1)


@pytest.mark.parametrize(
    "end_cb, lower_bound",
    [
        (end_run_basic, 1),
        (end_run_pause_resume, 2),
        (end_run_pause_pause, 1),
        (end_run_resume_resume, 3),
        (end_run_resume_pause, 2),
    ],
)
def test_runtime(relay_server, publish_util, mock_run, end_cb, lower_bound, user):

    run = mock_run(use_magic_mock=True)
    with relay_server() as relay:
        publish_util(run=run, end_cb=end_cb, initial_start=True)

    summary = relay.context.get_run_summary(run.id, include_private=True)
    assert summary["_wandb"]["runtime"] >= lower_bound
