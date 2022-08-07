import time

from wandb.sdk.wandb_settings import Source


def end_run_basic(interface):
    time.sleep(3)


def test_runtime_resume(
    publish_util,
    test_settings,
    mock_server,
):
    mock_server.ctx["resume"] = True
    test_settings.update(resume="allow", source=Source.INIT)

    ctx_util = publish_util(end_cb=end_run_basic, initial_start=True)
    assert ctx_util.summary_wandb["runtime"] >= 53
