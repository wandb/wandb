import copy
import platform

import numpy as np
import pytest
import wandb
from wandb.apis import public
from wandb.sdk import wandb_run

REFERENCE_ATTRIBUTES = set(
    [
        "alert",
        "config",
        "config_static",
        "define_metric",
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
        "link_artifact",
        "link_model",
        "log",
        "log_artifact",
        "log_code",
        "log_model",
        "mark_preempting",
        "name",
        "notes",
        "offline",
        "path",
        "project",
        "project_name",
        "project_url",
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
        "sweep_url",
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
    run = wandb_run.Run(settings=s, config=c)
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
    run = wandb_run.Run(settings=s, config=c, sweep_config=sw)
    assert dict(run.config) == dict(param1=2, param2=4, param3=9)


def test_run_sweep_overlap():
    s = wandb.Settings()
    c = dict(param1=2, param2=4)
    sw = dict(param2=8, param3=9)
    run = wandb_run.Run(settings=s, config=c, sweep_config=sw)
    assert dict(run.config) == dict(param1=2, param2=8, param3=9)


def test_run_deepcopy():
    s = wandb.Settings()
    c = dict(param1=2, param2=4)
    run = wandb_run.Run(settings=s, config=c)
    run2 = copy.deepcopy(run)
    assert id(run) == id(run2)


def test_finish_success(mock_run, parse_records, record_q):
    """Baseline test: finish with exit_code=0 sends exit record without preempting."""
    run = mock_run()
    run.finish(exit_code=0)

    parsed = parse_records(record_q)

    exit_records = list(parsed["exit"])
    assert len(exit_records) == 1
    assert exit_records[0].exit_code == 0
    assert exit_records[0].preempting is False


def test_finish_failure(mock_run, parse_records, record_q):
    """Baseline test: finish with non-zero exit code sends exit record without preempting."""
    run = mock_run()
    run.finish(exit_code=1)

    parsed = parse_records(record_q)

    exit_records = list(parsed["exit"])
    assert len(exit_records) == 1
    assert exit_records[0].exit_code == 1
    assert exit_records[0].preempting is False


def test_mark_preempting(mock_run, parse_records, record_q):
    run = mock_run()
    run.mark_preempting()

    parsed = parse_records(record_q)

    assert len(parsed.preempting) == 1
    assert parsed.records[-1].HasField("preempting")


def test_mark_preempting_then_finish(mock_run, parse_records, record_q):
    """Verify exit record has preempting flag set when mark_preempting is called."""
    run = mock_run()
    run.mark_preempting()
    run.finish(exit_code=1)

    parsed = parse_records(record_q)

    exit_records = list(parsed["exit"])
    assert len(exit_records) == 1
    assert exit_records[0].preempting is True
    assert exit_records[0].exit_code == 1


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


def test_public_api_uses_api_key(mock_run, mocker):
    api_key = "anything"

    mock_api_class = mocker.patch.object(public, "Api")
    mock_api_instance = mocker.MagicMock()
    mock_api_class.return_value = mock_api_instance
    run = mock_run(settings=wandb.Settings(api_key=api_key))

    api = run._public_api()

    mock_api_class.assert_called_once_with(
        # overrides from mock_run
        {
            "run": None,
            "entity": "",
            "project": "",
        },
        api_key=api_key,
    )
    assert api is mock_api_instance


def test_public_api_is_cached(mock_run, mocker):
    mock_api_class = mocker.patch.object(public, "Api")
    mock_api_instance = mocker.MagicMock()
    mock_api_class.return_value = mock_api_instance
    run = mock_run()

    api1 = run._public_api()
    api2 = run._public_api()

    assert api1 is api2
    assert api1 is run._cached_public_api
    mock_api_class.assert_called_once()
