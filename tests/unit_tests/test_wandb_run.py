import os
import pickle
import platform
import sys
from unittest import mock

import numpy as np
import pytest
import wandb
from wandb import wandb_sdk
from wandb.errors import MultiprocessError, UsageError


@pytest.mark.skipif(
    os.environ.get("WANDB_REQUIRE_SERVICE"), reason="different behavior with service"
)
def test_run_log_mp_error(wandb_init, test_settings):
    test_settings = test_settings({"strict": True})
    run = wandb_init(settings=test_settings)
    _init_pid = run._init_pid
    run._init_pid = _init_pid + 1
    with pytest.raises(MultiprocessError) as excinfo:
        run.log(dict(this=1))
        assert "`log` does not support multiprocessing" in str(excinfo.value)
    run._init_pid = _init_pid
    run.finish()


def test_log_code(wandb_init):
    run = wandb_init(mode="offline")
    with open("test.py", "w") as f:
        f.write('print("test")')
    with open("big_file.h5", "w") as f:
        f.write("Not that big")
    art = run.log_code()
    assert sorted(art.manifest.entries.keys()) == ["test.py"]
    run.finish()


def test_log_code_include(wandb_init):
    run = wandb_init(mode="offline")

    with open("test.py", "w") as f:
        f.write('print("test")')
    with open("test.cc", "w") as f:
        f.write("Not that big")

    art = run.log_code(include_fn=lambda p: p.endswith(".py") or p.endswith(".cc"))
    assert sorted(art.manifest.entries.keys()) == ["test.cc", "test.py"]

    run.finish()


def test_log_code_custom_root(wandb_init):
    run = wandb_init(mode="offline")
    with open("test.py", "w") as f:
        f.write('print("test")')
    os.mkdir("custom")
    os.chdir("custom")
    with open("test.py", "w") as f:
        f.write('print("test")')
    art = run.log_code(root="../")
    assert sorted(art.manifest.entries.keys()) == ["custom/test.py", "test.py"]
    run.finish()


@pytest.mark.parametrize("project_name", ["test:?", "test" * 33])
def test_invalid_project_name(user, project_name):
    with pytest.raises(UsageError) as e:
        wandb.init(project=project_name)
        assert 'Invalid project name "{project_name}"' in str(e.value)


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


def test_except_hook(test_settings):
    # Test to make sure we respect excepthooks by 3rd parties like pdb
    errs = []

    def hook(etype, val, tb):
        return errs.append(str(val))

    sys.excepthook = hook

    # We cant use raise statement in pytest context
    def raise_(exc):
        return sys.excepthook(type(exc), exc, None)

    raise_(Exception("Before wandb.init()"))

    run = wandb.init(mode="offline", settings=test_settings())

    old_stderr_write = sys.stderr.write
    stderr = []
    sys.stderr.write = stderr.append

    raise_(Exception("After wandb.init()"))

    assert errs == ["Before wandb.init()", "After wandb.init()"]

    # make sure wandb prints the traceback
    assert "".join(stderr) == "Exception: After wandb.init()\n"

    sys.stderr.write = old_stderr_write
    run.finish()


def assertion(run_id, found, stderr):
    msg = (
        "`resume` will be ignored since W&B syncing is set to `offline`. "
        f"Starting a new run with run id {run_id}"
    )
    return msg in stderr if found else msg not in stderr


@pytest.mark.parametrize(
    "resume, found",
    [
        ("auto", True),
        ("allow", True),
        ("never", True),
        ("must", True),
        ("", False),
        (0, False),
        (True, True),
        (None, False),
    ],
)
def test_offline_resume(test_settings, capsys, resume, found):
    run = wandb.init(mode="offline", resume=resume, settings=test_settings())
    captured = capsys.readouterr()
    assert assertion(run.id, found, captured.err)
    run.finish()


def test_unlogged_artifact_in_config(user, test_settings):
    run = wandb.init(settings=test_settings())
    artifact = wandb.Artifact("my-arti", type="dataset")
    with pytest.raises(Exception) as e_info:
        run.config.dataset = artifact
        assert (
            str(e_info.value)
            == "Cannot json encode artifact before it has been logged or in offline mode."
        )
    run.finish()


def test_media_in_config(runner, user, test_settings):
    with runner.isolated_filesystem():
        run = wandb.init(settings=test_settings())
        with pytest.raises(ValueError):
            run.config["image"] = wandb.Image(np.random.randint(0, 255, (100, 100, 3)))
        run.finish()


def test_init_with_settings(wandb_init, test_settings):
    # test that when calling `wandb.init(settings=wandb.Settings(...))`,
    # the settings are passed with Source.INIT as the source
    test_settings = test_settings()
    test_settings.update(_disable_stats=True)
    run = wandb_init(settings=test_settings)
    assert run.settings._disable_stats
    assert (
        run.settings.__dict__["_disable_stats"].source
        == wandb_sdk.wandb_settings.Source.INIT
    )
    run.finish()


def test_attach_same_process(user, test_settings):
    with mock.patch.dict("os.environ", WANDB_REQUIRE_SERVICE="True"):
        with pytest.raises(RuntimeError) as excinfo:
            run = wandb.init(settings=test_settings())
            new_run = pickle.loads(pickle.dumps(run))
            new_run.log({"a": 2})
        run.finish()
    assert "attach in the same process is not supported" in str(excinfo.value)


def test_deprecated_feature_telemetry(relay_server, test_settings, user):
    with relay_server() as relay:
        run = wandb.init(
            config_include_keys=("lol",),
            settings=test_settings(),
        )
        # use deprecated features
        _ = [
            run.mode,
            run.save(),
            run.join(),
        ]
        telemetry = relay.context.get_run_telemetry(run.id)
        # TelemetryRecord field 10 is Deprecated,
        # whose fields 2-4 correspond to deprecated wandb.run features
        # fields 7 & 8 are deprecated wandb.init kwargs
        telemetry_deprecated = telemetry.get("10", [])
        assert (
            (2 in telemetry_deprecated)
            and (3 in telemetry_deprecated)
            and (4 in telemetry_deprecated)
            and (7 in telemetry_deprecated)
        )


# test that information about validation errors in wandb.Settings is included in telemetry
def test_settings_validation_telemetry(relay_server, test_settings, capsys, user):
    test_settings = test_settings()
    test_settings.update(api_key=123)
    captured = capsys.readouterr().err
    msg = "Invalid value for property api_key: 123"
    assert msg in captured

    with relay_server() as relay:
        run = wandb.init(settings=test_settings)
        telemetry = relay.context.get_run_telemetry(run.id)
        # TelemetryRecord field 11 is Issues,
        # whose field 1 corresponds to validation warnings in Settings
        assert 1 in telemetry.get("11", [])
        run.finish()


# test that information about validation errors in wandb.Settings is included in telemetry
def test_settings_preprocessing_telemetry(relay_server, test_settings, capsys, user):
    with mock.patch.dict("os.environ", WANDB_QUIET="cat"):
        with relay_server() as relay:
            run = wandb.init(settings=test_settings())
            captured = capsys.readouterr().err
            msg = "Unable to preprocess value for property quiet: cat"
            assert (
                msg in captured and "This will raise an error in the future" in captured
            )
            telemetry = relay.context.get_run_telemetry(run.id)
            # TelemetryRecord field 11 is Issues,
            # whose field 3 corresponds to preprocessing warnings in Settings
            assert 3 in telemetry.get("11", [])
            run.finish()


def test_settings_unexpected_args_telemetry(runner, relay_server, capsys, user):
    with runner.isolated_filesystem():
        with relay_server() as relay:
            run = wandb.init(settings=wandb.Settings(blah=3))
            captured = capsys.readouterr().err
            msg = "Ignoring unexpected arguments: ['blah']"
            assert msg in captured
            telemetry = relay.context.get_run_telemetry(run.id)
            # TelemetryRecord field 11 is Issues,
            # whose field 2 corresponds to unexpected arguments in Settings
            assert 2 in telemetry.get("11", [])
            run.finish()
