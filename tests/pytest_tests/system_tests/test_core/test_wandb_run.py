import os
import pickle
import sys
from unittest import mock

import numpy as np
import pytest
import wandb
from wandb import wandb_sdk
from wandb.errors import UsageError


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


def test_resume_must_failure(wandb_init):
    with pytest.raises(wandb.UsageError):
        wandb_init(reinit=True, resume="must")


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
