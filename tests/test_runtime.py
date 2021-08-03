import time
from wandb.proto import wandb_internal_pb2 as pb
import pytest


def end_run_basic(interface):
    time.sleep(3)


def end_run_pause_resume(interface):
    time.sleep(3)
    interface.publish_pause()
    time.sleep(3)
    interface.publish_resume()
    time.sleep(3)


def end_run_pause_pause(interface):
    time.sleep(3)
    interface.publish_pause()
    time.sleep(3)
    interface.publish_pause()
    time.sleep(3)


def end_run_resume_resume(interface):
    time.sleep(3)
    interface.publish_resume()
    time.sleep(3)
    interface.publish_resume()
    time.sleep(3)


def end_run_resume_pause(interface):
    time.sleep(3)
    interface.publish_resume()
    time.sleep(3)
    interface.publish_pause()
    time.sleep(3)


def test_runtime_resume_point_2(
    publish_util, test_settings, mock_server, start_run,
):
    def end_run_basic(interface):
        time.sleep(2)

    mock_server.ctx["resume"] = True
    test_settings.resume = "allow"

    ctx_util = publish_util(begin_cb=start_run, end_cb=end_run_basic)
    assert ctx_util.summary_wandb["runtime"] >= 53


def test_runtime_resume_point_1(
    test_settings, live_mock_server, parse_ctx,
):
    import wandb

    test_settings.resume = "allow"
    _ = live_mock_server.set_ctx({"resume": True})

    run = wandb.init(settings=test_settings)
    time.sleep(3)
    run.finish()
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    assert ctx_util.summary_wandb["runtime"] >= 53


@pytest.mark.parametrize(
    "end_cb, lower_bound",
    [
        (end_run_basic, 3),
        (end_run_pause_resume, 6),
        (end_run_pause_pause, 3),
        (end_run_resume_resume, 9),
        (end_run_resume_pause, 6),
    ],
)
def test_runtime(publish_util, start_run, end_cb, lower_bound):

    ctx_util = publish_util(begin_cb=start_run, end_cb=end_cb)

    assert ctx_util.summary_wandb["runtime"] >= lower_bound
