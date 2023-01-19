import os
import platform

import numpy as np
import pytest
import wandb
from wandb import wandb_sdk


def test_run_step_property(mock_run):
    run = mock_run()
    run.log(dict(this=1))
    run.log(dict(this=2))
    assert run.step == 2


def test_log_avoids_mutation(mock_run):
    run = mock_run()
    d = dict(this=1)
    run.log(d)
    assert d == dict(this=1)


def test_display(mock_run):
    run = mock_run(settings=wandb.Settings(mode="offline"))
    assert run.display() is False


@pytest.mark.parametrize(
    "config, sweep_config, expected_config",
    [
        (
            dict(param1=2, param2=4),
            dict(),
            dict(param1=2, param2=4),
        ),
        (
            dict(param1=2, param2=4),
            dict(param3=9),
            dict(param1=2, param2=4, param3=9),
        ),
        (
            dict(param1=2, param2=4),
            dict(param2=8, param3=9),
            dict(param1=2, param2=8, param3=9),
        ),
    ],
)
def test_run_config(mock_run, config, sweep_config, expected_config):
    run = mock_run(config=config, sweep_config=sweep_config)
    assert dict(run.config) == expected_config


def test_run_urls(mock_run):
    base_url = "https://my.cool.site.com"
    entity = "me"
    project = "lol"
    run_id = "my-run"
    run = mock_run(
        settings=wandb.Settings(
            base_url=base_url,
            entity=entity,
            project=project,
            run_id=run_id,
        )
    )
    assert run.get_project_url() == f"{base_url}/{entity}/{project}"
    assert run.get_url() == f"{base_url}/{entity}/{project}/runs/{run.id}"


def test_run_publish_config(mock_run, parse_records, record_q):
    run = mock_run()
    run.config.t = 1
    run.config.t2 = 2

    parsed = parse_records(record_q)

    assert len(parsed.records) == 2
    assert len(parsed.summary) == 0

    config = parsed.config
    assert len(config) == 2
    assert config[0]["t"] == "1"
    assert config[1]["t2"] == "2"


def test_run_publish_history(mock_run, parse_records, record_q):
    run = mock_run()
    run.log(dict(this=1))
    run.log(dict(that=2))

    parsed = parse_records(record_q)

    assert len(parsed.records) == 2
    assert len(parsed.summary) == 0

    history = parsed.history or parsed.partial_history
    assert len(history) == 2
    assert history[0]["this"] == "1"
    assert history[1]["that"] == "2"


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="numpy.float128 does not exist on windows",
)
@pytest.mark.skipif(
    platform.system() == "Darwin" and platform.machine() == "arm64",
    reason="numpy.float128 does not exist on Macs with the Apple M1 chip",
)
# @pytest.mark.GH2255 #TODO think of a marker format for tests that fix reported issues
def test_numpy_high_precision_float_downcasting(mock_run, parse_records, record_q):
    run = mock_run()
    run.log(dict(this=np.float128(0.0)))

    parsed = parse_records(record_q)

    assert len(parsed.records) == 1
    assert len(parsed.summary) == 0

    history = parsed.history or parsed.partial_history
    assert len(history) == 1
    assert history[0]["this"] == "0.0"


def test_mark_preempting(mock_run, parse_records, record_q):
    run = mock_run()
    run.log(dict(this=1))
    run.log(dict(that=2))
    run.mark_preempting()

    parsed = parse_records(record_q)

    assert len(parsed.records) == 3

    assert len(parsed.preempting) == 1
    assert parsed.records[-1].HasField("preempting")


def test_run_pub_config(mock_run, record_q, parse_records):
    run = mock_run()
    run.config.t = 1
    run.config.t2 = 2

    parsed = parse_records(record_q)
    assert len(parsed.records) == 2
    assert len(parsed.summary) == 0
    assert len(parsed.config) == 2
    assert parsed.config[0]["t"] == "1"
    assert parsed.config[1]["t2"] == "2"


def test_run_pub_history(mock_run, record_q, parse_records):
    run = mock_run()
    run.log(dict(this=1))
    run.log(dict(that=2))

    parsed = parse_records(record_q)
    assert len(parsed.records) == 2
    assert len(parsed.summary) == 0
    history = parsed.history or parsed.partial_history
    assert len(history) == 2
    assert history[0]["this"] == "1"
    assert history[1]["that"] == "2"


def test_deprecated_run_log_sync(mock_run, capsys):
    run = mock_run()
    run.log(dict(this=1), sync=True)
    _, stderr = capsys.readouterr()
    assert (
        "`sync` argument is deprecated and does not affect the behaviour of `wandb.log`"
        in stderr
    )


def test_run_log_mp_warn(mock_run, capsys):
    run = mock_run()
    run._init_pid += 1
    run.log(dict(this=1))
    _, stderr = capsys.readouterr()
    assert (
        f"`log` ignored (called from pid={os.getpid()}, "
        f"`init` called from pid={run._init_pid})" in stderr
    )


def test_use_artifact_offline(mock_run):
    run = mock_run(settings=wandb.Settings(mode="offline"))
    with pytest.raises(Exception) as e_info:
        run.use_artifact("boom-data")
        assert str(e_info.value) == "Cannot use artifact when in offline mode."


def test_run_basic():
    s = wandb.Settings()
    c = dict(param1=2, param2=4)
    run = wandb_sdk.wandb_run.Run(settings=s, config=c)
    assert dict(run.config) == dict(param1=2, param2=4)


def test_run_sweep():
    s = wandb.Settings()
    c = dict(param1=2, param2=4)
    sw = dict(param3=9)
    run = wandb_sdk.wandb_run.Run(settings=s, config=c, sweep_config=sw)
    assert dict(run.config) == dict(param1=2, param2=4, param3=9)


def test_run_sweep_overlap():
    s = wandb.Settings()
    c = dict(param1=2, param2=4)
    sw = dict(param2=8, param3=9)
    run = wandb_sdk.wandb_run.Run(settings=s, config=c, sweep_config=sw)
    assert dict(run.config) == dict(param1=2, param2=8, param3=9)
