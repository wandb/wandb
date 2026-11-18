import copy
import platform
import time
from uuid import UUID

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
        "group",
        "id",
        "job_type",
        "link_artifact",
        "link_model",
        "log",
        "log_artifact",
        "log_code",
        "log_events",
        "log_model",
        "mark_preempting",
        "name",
        "notes",
        "offline",
        "path",
        "pin_config_keys",
        "project",
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
        "sync_dir",
        "tags",
        "to_html",
        "unwatch",
        "upsert_artifact",
        "url",
        "use_artifact",
        "use_model",
        "watch",
        "write_logs",
    ]
)


def test_run_step_property():
    with wandb.init(mode="offline") as run:
        run.log(dict(this=1))
        run.log(dict(this=2))
        assert run.step == 2


def test_log_avoids_mutation():
    with wandb.init(mode="offline") as run:
        d = dict(this=1)
        run.log(d)
        assert d == dict(this=1)


def test_display():
    with wandb.init(mode="offline") as run:
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
    assert run.project_url == f"{base_url}/{entity}/{project}"
    assert run.url == f"{base_url}/{entity}/{project}/runs/{run.id}"


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


@pytest.mark.parametrize(
    "kwargs, field",
    [
        ({"type": ""}, "type"),
        ({"type": "é" * 2048 + "x"}, "type"),
        ({"title": ""}, "title"),
        ({"step": -1}, "step"),
        ({"step": 1.0}, "step"),
        ({"step": True}, "step"),
        ({"step_metric": "tokens"}, "step_metric_value"),
        ({"step_metric_value": 42.0}, "step_metric"),
        ({"step_metric": b"tokens", "step_metric_value": 0}, "step_metric"),
        ({"step_metric": "é" * 2048 + "x", "step_metric_value": 0}, "step_metric"),
        ({"step_metric": "tokens", "step_metric_value": "42"}, "step_metric_value"),
        ({"step_metric": "tokens", "step_metric_value": 10**400}, "step_metric_value"),
        (
            {"step_metric": "tokens", "step_metric_value": float("inf")},
            "step_metric_value",
        ),
        ({"severity": "CRITICAL"}, "severity"),
        ({"attributes": []}, "attributes"),
        ({"attributes": ()}, "attributes"),
        ({"attributes": ["name"]}, "attributes"),
        ({"attributes": {"": True}}, "attribute"),
        ({"attributes": {"has-dash": True}}, "attribute"),
        ({"attributes": {"accent.é": True}}, "attribute"),
        ({"attributes": {"x" * 129: True}}, "attribute"),
        ({"attributes": {"x\n": True}}, "attribute"),
        ({"attributes": {"_custom": True}}, "attribute"),
        ({"attributes": {f"key{i}": i for i in range(33)}}, "attribute"),
        ({"title": "é" * 2049}, "title"),
        ({"attributes": {"text": "é" * 2049}}, "attribute"),
        ({"attributes": {"obj": []}}, "attribute"),
        ({"attributes": {"rate": float("nan")}}, "attribute"),
    ],
)
def test_log_events_rejects_invalid_arguments(mock_run, record_q, kwargs, field):
    run = mock_run()

    with pytest.raises(ValueError, match=field):
        run.log_events(**({"type": "checkpoint", "title": "Saved"} | kwargs))

    assert record_q.empty()


def test_log_events_accepts_maximum_type_and_metric_bytes(mock_run, record_q):
    run = mock_run()
    name = "é" * 2048

    run.log_events(type=name, title="Saved", step_metric=name, step_metric_value=42)

    event = record_q.get_nowait().event
    assert event.type == name
    assert event.step_metric == name
    assert event.step_metric_value == 42.0


@pytest.mark.parametrize(
    "key",
    [
        "step",
        "severity",
        "severity_rank",
        "severity_original",
        "event_type",
        "source_sdk",
        "step_metric",
        "step_metric_value",
        "tenant",
        "project",
        "timestamp",
        "accepted",
        "run",
        "source",
        "id",
    ],
)
def test_log_events_rejects_reserved_attributes(mock_run, key):
    run = mock_run()

    with pytest.raises(ValueError, match=key):
        run.log_events(type="checkpoint", title="Saved", attributes={key: True})


def test_log_events_publishes_typed_record(mock_run, record_q, monkeypatch):
    run = mock_run()
    monkeypatch.setattr(time, "time_ns", lambda: 1_700_000_000_123_456_789)

    run.log_events(
        type="checkpoint",
        title="Saved",
        step=0,
        step_metric="tokens_seen",
        step_metric_value=0.0,
        severity="wArN",
        attributes={"text": "é" * 2048, "count": 0, "rate": 0.5, "ok": False},
    )

    record = record_q.get_nowait()
    record = type(record).FromString(record.SerializeToString())
    assert record.WhichOneof("record_type") == "event"
    assert not record.control.local
    event = record.event
    assert UUID(event.event_id).version == 4
    assert event.type == "checkpoint"
    assert event.title == "Saved"
    assert event.severity == "WARN"
    assert event.HasField("step") and event.step == 0
    assert event.step_metric == "tokens_seen"
    assert event.HasField("step_metric_value") and event.step_metric_value == 0.0
    assert event.timestamp_ms == 1_700_000_000_123
    assert set(event.attributes) == {"text", "count", "rate", "ok"}
    assert event.attributes["text"].string_value == "é" * 2048
    assert event.attributes["count"].WhichOneof("value") == "int_value"
    assert event.attributes["count"].int_value == 0
    assert event.attributes["rate"].double_value == 0.5
    assert event.attributes["ok"].WhichOneof("value") == "bool_value"
    assert not event.attributes["ok"].bool_value


def test_log_events_publishes_distinct_ids_and_leaves_implicit_step_unset(
    mock_run, record_q
):
    run = mock_run()

    for _ in range(2):
        run.log_events(type="checkpoint", title="Saved")

    first = record_q.get_nowait().event
    second = record_q.get_nowait().event
    assert first.event_id != second.event_id
    assert first.severity == "INFO"
    assert not first.HasField("step")
    assert not first.HasField("step_metric_value")


def test_log_events_rejects_finished_run(mock_run):
    run = mock_run()
    run._is_finished = True

    with pytest.raises(wandb.errors.UsageError, match="log_events"):
        run.log_events(type="checkpoint", title="Saved")


def test_log_events_is_noop_on_disabled_run():
    with wandb.init(mode="disabled") as run:
        assert run.log_events(type="", title="") is None


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
            "base_url": "https://api.forge.coreweave.com",
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
