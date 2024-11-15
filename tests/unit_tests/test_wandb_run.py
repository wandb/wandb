import copy
import os
import platform

import numpy as np
import pytest
import wandb
import wandb.errors
from wandb import wandb_sdk

REFERENCE_ATTRIBUTES = set(
    [
        "alert",
        "config",
        "config_static",
        "define_metric",
        "detach",
        "dir",
        "disabled",
        "display",
        "entity",
        "finish",
        "finish_artifact",
        "get_project_url",
        "get_sweep_url",
        "get_url",
        "group",
        "id",
        "job_type",
        "join",
        "link_artifact",
        "link_model",
        "log",
        "log_artifact",
        "log_code",
        "log_model",
        "mark_preempting",
        "mode",
        "name",
        "notes",
        "offline",
        "path",
        "project",
        "project_name",
        "restore",
        "resumed",
        "save",
        "settings",
        "start_time",
        "starting_step",
        "status",
        "step",
        "summary",
        "sweep_id",
        "tags",
        "to_html",
        "unwatch",
        "upsert_artifact",
        "url",
        "use_artifact",
        "use_model",
        "watch",
    ]
)


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


def test_deprecated_run_log_sync(mock_run, mock_wandb_log):
    run = mock_run()

    run.log(dict(this=1), sync=True)

    assert mock_wandb_log.warned(
        "`sync` argument is deprecated"
        " and does not affect the behaviour of `wandb.log`"
    )


def test_run_log_mp_warn(mock_run, test_settings, monkeypatch, mock_wandb_log):
    monkeypatch.setenv("WANDB_DISABLE_SERVICE", "true")
    settings = test_settings()
    settings.update_from_env_vars(os.environ)

    run = mock_run(settings=settings)
    run._init_pid = os.getpid()
    run._init_pid += 1
    run.log(dict(this=1))

    assert mock_wandb_log.warned(
        f"`log` ignored (called from pid={os.getpid()}, "
        f"`init` called from pid={run._init_pid})"
    )


def test_use_artifact_offline(mock_run):
    run = mock_run(settings=wandb.Settings(mode="offline"))
    with pytest.raises(Exception) as e_info:
        run.use_artifact("boom-data")
        assert str(e_info.value) == "Cannot use artifact when in offline mode."


def test_run_basic():
    s = wandb.Settings()
    c = dict(
        param1=2,
        param2=4,
        param3=set(range(10)),
        param4=list(range(10, 20)),
        param5=tuple(range(20, 30)),
        dict_param=dict(
            a=list(range(10)), b=tuple(range(10, 20)), c=set(range(20, 30))
        ),
    )
    run = wandb_sdk.wandb_run.Run(settings=s, config=c)
    assert dict(run.config) == dict(
        param1=2,
        param2=4,
        param3=list(range(10)),
        param4=list(range(10, 20)),
        param5=list(range(20, 30)),
        dict_param=dict(
            a=list(range(10)), b=list(range(10, 20)), c=list(range(20, 30))
        ),
    )


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


def test_run_deepcopy():
    s = wandb.Settings()
    c = dict(param1=2, param2=4)
    run = wandb_sdk.wandb_run.Run(settings=s, config=c)
    run2 = copy.deepcopy(run)
    assert id(run) == id(run2)


@pytest.mark.parametrize(
    "settings, expected",
    [
        ({}, False),
        ({"resume": False}, False),
        ({"resume": True}, True),
        ({"resume": "auto"}, True),
        ({"resume": "allow"}, True),
        ({"resume": "never"}, True),
        ({"resume": "must"}, True),
    ],
)
def test_resumed_run_resume_file_state(mocker, mock_run, tmp_path, settings, expected):
    tmp_file = tmp_path / "test_resume.json"
    tmp_file.write_text("{'run_id': 'test'}")

    mocker.patch("wandb.sdk.wandb_settings.Settings.resume_fname", tmp_file)

    run = mock_run(use_magic_mock=True, settings=settings)
    run._on_ready()

    assert tmp_file.exists() == expected


def test_new_attributes(mock_run):
    run = mock_run()
    current_attributes = set([attr for attr in dir(run) if not attr.startswith("_")])
    added_attributes = current_attributes - REFERENCE_ATTRIBUTES
    removed_attributes = REFERENCE_ATTRIBUTES - current_attributes
    assert not added_attributes, f"New attributes: {added_attributes}"
    assert not removed_attributes, f"Removed attributes: {removed_attributes}"
