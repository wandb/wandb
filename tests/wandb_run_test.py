"""
config tests.
"""

import os
import sys
import numpy as np
import platform
import pytest
from unittest import mock

import wandb
from wandb import wandb_sdk
from wandb.errors import UsageError
from wandb.proto.wandb_internal_pb2 import RunPreemptingRecord


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


def test_run_pub_config(fake_run, record_q, records_util):
    run = fake_run()
    run.config.t = 1
    run.config.t2 = 2

    r = records_util(record_q)
    assert len(r.records) == 2
    assert len(r.summary) == 0
    configs = r.configs
    assert len(configs) == 2
    # TODO(jhr): check config vals


def test_run_pub_history(fake_run, record_q, records_util):
    run = fake_run()
    run.log(dict(this=1))
    run.log(dict(that=2))

    r = records_util(record_q)
    assert len(r.records) == 2
    assert len(r.summary) == 0
    history = r.history
    assert len(history) == 2
    # TODO(jhr): check history vals


@pytest.mark.skipif(
    platform.system() == "Windows", reason="numpy.float128 does not exist on windows"
)
def test_numpy_high_precision_float_downcasting(fake_run, record_q, records_util):
    # CLI: GH2255
    run = fake_run()
    run.log(dict(this=np.float128(0.0)))
    r = records_util(record_q)
    assert len(r.records) == 1
    assert len(r.summary) == 0
    history = r.history
    assert len(history) == 1

    found = False
    for item in history[0].item:
        if item.key == "this":
            assert item.value_json == "0.0"
            found = True
    assert found


def test_log_code_settings(live_mock_server, test_settings):
    with open("test.py", "w") as f:
        f.write('print("test")')
    test_settings.update(
        save_code=True, code_dir=".", source=wandb.sdk.wandb_settings.Source.INIT
    )
    run = wandb.init(settings=test_settings)
    run.finish()
    ctx = live_mock_server.get_ctx()
    artifact_name = list(ctx["artifacts"].keys())[0]
    assert artifact_name == "source-" + run.id


@pytest.mark.parametrize("save_code", [True, False])
def test_log_code_env(live_mock_server, test_settings, save_code):
    # test for WB-7468
    with mock.patch.dict("os.environ", WANDB_SAVE_CODE=str(save_code).lower()):
        with open("test.py", "w") as f:
            f.write('print("test")')

        # first, ditch user preference for code saving
        # since it has higher priority for policy settings
        live_mock_server.set_ctx({"code_saving_enabled": None})
        # note that save_code is a policy by definition
        test_settings.update(
            save_code=None,
            code_dir=".",
            source=wandb.sdk.wandb_settings.Source.SETTINGS,
        )
        run = wandb.init(settings=test_settings)
        assert run._settings.save_code is save_code
        run.finish()

        ctx = live_mock_server.get_ctx()
        artifact_names = list(ctx["artifacts"].keys())
        if save_code:
            assert artifact_names[0] == "source-" + run.id
        else:
            assert len(artifact_names) == 0


def test_log_code(test_settings):
    run = wandb.init(mode="offline", settings=test_settings)
    with open("test.py", "w") as f:
        f.write('print("test")')
    with open("big_file.h5", "w") as f:
        f.write("Not that big")
    art = run.log_code()
    assert sorted(art.manifest.entries.keys()) == ["test.py"]
    run.finish()


def test_log_code_include(test_settings):
    run = wandb.init(mode="offline", settings=test_settings)
    with open("test.py", "w") as f:
        f.write('print("test")')
    with open("test.cc", "w") as f:
        f.write("Not that big")
    art = run.log_code(include_fn=lambda p: p.endswith(".py") or p.endswith(".cc"))
    assert sorted(art.manifest.entries.keys()) == ["test.cc", "test.py"]
    run.finish()


def test_log_code_custom_root(test_settings):
    with open("test.py", "w") as f:
        f.write('print("test")')
    os.mkdir("custom")
    os.chdir("custom")
    with open("test.py", "w") as f:
        f.write('print("test")')
    run = wandb.init(mode="offline", settings=test_settings)
    art = run.log_code(root="../")
    assert sorted(art.manifest.entries.keys()) == ["custom/test.py", "test.py"]
    run.finish()


def test_display(test_settings):
    run = wandb.init(mode="offline", settings=test_settings)
    assert run.display() is False
    run.finish()


def test_mark_preempting(fake_run, record_q, records_util):
    run = fake_run()
    run.log(dict(this=1))
    run.log(dict(that=2))
    run.mark_preempting()

    r = records_util(record_q)
    assert len(r.records) == 3
    assert type(r.records[-1]) == RunPreemptingRecord


def test_except_hook(test_settings):
    # Test to make sure we respect excepthooks by 3rd parties like pdb
    errs = []
    hook = lambda etype, val, tb: errs.append(str(val))
    sys.excepthook = hook

    # We cant use raise statement in pytest context
    raise_ = lambda exc: sys.excepthook(type(exc), exc, None)

    raise_(Exception("Before wandb.init()"))

    run = wandb.init(mode="offline", settings=test_settings)

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
    run = wandb.init(mode="offline", resume=resume, settings=test_settings)
    captured = capsys.readouterr()
    assert assertion(run.id, found, captured.err)
    run.finish()


@pytest.mark.parametrize("empty_query", [True, False])
@pytest.mark.parametrize("local_none", [True, False])
@pytest.mark.parametrize("outdated", [True, False])
def test_local_warning(
    live_mock_server, test_settings, capsys, outdated, empty_query, local_none
):
    live_mock_server.set_ctx(
        {"out_of_date": outdated, "empty_query": empty_query, "local_none": local_none}
    )
    run = wandb.init(settings=test_settings)
    run.finish()
    captured = capsys.readouterr().err

    msg = "version of W&B Local to get the latest features"

    if empty_query:
        assert msg in captured
    elif local_none:
        assert msg not in captured
    else:
        assert msg in captured if outdated else msg not in captured


@pytest.mark.parametrize("project_name", ["test:?", "test" * 33])
def test_invalid_project_name(live_mock_server, project_name):
    with pytest.raises(UsageError) as e:
        wandb.init(project=project_name)
        assert 'Invalid project name "{project_name}"' in str(e.value)


def test_use_artifact_offline(live_mock_server, test_settings):
    run = wandb.init(mode="offline")
    with pytest.raises(Exception) as e_info:
        run.use_artifact("boom-data")
        assert str(e_info.value) == "Cannot use artifact when in offline mode."
    run.finish()


def test_run_urls(test_settings):
    base_url = "https://my.cool.site.com"
    entity = "me"
    project = "test"
    test_settings.update(dict(base_url=base_url, entity=entity, project=project))
    run = wandb.init(settings=test_settings)
    assert run.get_project_url() == f"{base_url}/{entity}/{project}"
    assert run.get_url() == f"{base_url}/{entity}/{project}/runs/{run.id}"
    run.finish


def test_use_artifact(live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
    artifact = wandb.Artifact("arti", type="dataset")
    run.use_artifact(artifact)
    artifact.wait()
    assert artifact.digest == "abc123"
    run.finish()


def test_artifacts_in_config(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)

    artifact = run.use_artifact("boom-data")
    logged_artifact = wandb.Artifact("my-arti", type="dataset")
    run.log_artifact(logged_artifact)
    logged_artifact.wait()
    run.config.dataset = artifact
    run.config.logged_artifact = logged_artifact
    run.config.update({"myarti": artifact})
    with pytest.raises(ValueError) as e_info:
        run.config.nested_dataset = {"nested": artifact}
        assert (
            str(e_info.value)
            == "Instances of wandb.Artifact and wandb.apis.public.Artifact can only be top level keys in wandb.config"
        )

    with pytest.raises(ValueError) as e_info:
        run.config.dict_nested = {"one_nest": {"two_nest": artifact}}
        assert (
            str(e_info.value)
            == "Instances of wandb.Artifact and wandb.apis.public.Artifact can only be top level keys in wandb.config"
        )

    with pytest.raises(ValueError) as e_info:
        run.config.update({"one_nest": {"two_nest": artifact}})
        assert (
            str(e_info.value)
            == "Instances of wandb.Artifact and wandb.apis.public.Artifact can only be top level keys in wandb.config"
        )
    run.finish()
    ctx = parse_ctx(live_mock_server.get_ctx())
    assert ctx.config_user["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact._sequence_name,
        "usedAs": "dataset",
    }

    assert ctx.config_user["myarti"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact._sequence_name,
        "usedAs": "myarti",
    }

    assert ctx.config_user["logged_artifact"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": logged_artifact.id,
        "version": "v0",
        "sequenceName": logged_artifact.name.split(":")[0],
        "usedAs": "logged_artifact",
    }


def test_unlogged_artifact_in_config(live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
    artifact = wandb.Artifact("my-arti", type="dataset")
    with pytest.raises(Exception) as e_info:
        run.config.dataset = artifact
        assert (
            str(e_info.value)
            == "Cannot json encode artifact before it has been logged or in offline mode."
        )
    run.finish()


def test_artifact_string_run_config_init(live_mock_server, test_settings, parse_ctx):
    config = {"dataset": "wandb-artifact://boom-data"}
    run = wandb.init(settings=test_settings, config=config)
    run.finish()
    ctx = parse_ctx(live_mock_server.get_ctx())

    assert ctx.config_user["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": run.config.dataset.id,
        "version": "v0",
        "sequenceName": run.config.dataset._sequence_name,
        "usedAs": "dataset",
    }


def test_artifact_string_run_config_set_item(
    runner, live_mock_server, test_settings, parse_ctx
):
    run = wandb.init(settings=test_settings)
    run.config.dataset = "wandb-artifact://boom-data"
    run.finish()
    ctx = parse_ctx(live_mock_server.get_ctx())
    assert ctx.config_user["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": run.config.dataset.id,
        "version": "v0",
        "sequenceName": run.config.dataset._sequence_name,
        "usedAs": "dataset",
    }


def test_artifact_string_run_config_update(
    runner, live_mock_server, test_settings, parse_ctx
):
    run = wandb.init(settings=test_settings)
    run.config.update({"dataset": "wandb-artifact://boom-data"})
    run.finish()
    ctx = parse_ctx(live_mock_server.get_ctx())
    assert ctx.config_user["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": run.config.dataset.id,
        "version": "v0",
        "sequenceName": run.config.dataset._sequence_name,
        "usedAs": "dataset",
    }


def test_public_artifact_run_config_init(
    live_mock_server, test_settings, api, parse_ctx
):
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    config = {"dataset": art}
    run = wandb.init(settings=test_settings, config=config)
    assert run.config.dataset == art
    run.finish()
    ctx = parse_ctx(live_mock_server.get_ctx())
    print(run.config.dataset)
    assert ctx.config_user["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": art.id,
        "version": "v0",
        "sequenceName": art._sequence_name,
        "usedAs": "dataset",
    }


def test_public_artifact_run_config_set_item(
    live_mock_server, test_settings, api, parse_ctx
):
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    run = wandb.init(settings=test_settings)
    run.config.dataset = art
    assert run.config.dataset == art
    run.finish()
    ctx = parse_ctx(live_mock_server.get_ctx())
    assert ctx.config_user["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": art.id,
        "version": "v0",
        "sequenceName": art._sequence_name,
        "usedAs": "dataset",
    }


def test_public_artifact_run_config_update(
    live_mock_server, test_settings, api, parse_ctx
):
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    config = {"dataset": art}
    run = wandb.init(settings=test_settings)
    run.config.update(config)
    assert run.config.dataset == art
    run.finish()
    ctx = parse_ctx(live_mock_server.get_ctx())
    assert ctx.config_user["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": art.id,
        "version": "v0",
        "sequenceName": art._sequence_name,
        "usedAs": "dataset",
    }


def test_wandb_artifact_init_config(runner, live_mock_server, test_settings, parse_ctx):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
        artifact = wandb.Artifact("test_reference_download", "dataset")
        artifact.add_file("file1.txt")
        artifact.add_reference(
            "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
        )
        config = {"test_reference_download": artifact}
        run = wandb.init(settings=test_settings, config=config)
        assert run.config.test_reference_download == artifact
        run.finish()
        ctx = parse_ctx(live_mock_server.get_ctx())
        assert ctx.config_user["test_reference_download"] == {
            "_type": "artifactVersion",
            "_version": "v0",
            "id": artifact.id,
            "version": "v0",
            "sequenceName": artifact.name.split(":")[0],
            "usedAs": "test_reference_download",
        }


def test_wandb_artifact_config_set_item(
    runner, live_mock_server, test_settings, parse_ctx
):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
        artifact = wandb.Artifact("test_reference_download", "dataset")
        artifact.add_file("file1.txt")
        artifact.add_reference(
            "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
        )
        run = wandb.init(settings=test_settings)
        run.config.test_reference_download = artifact
        assert run.config.test_reference_download == artifact
        run.finish()
        ctx = parse_ctx(live_mock_server.get_ctx())
        print(ctx.config_user["test_reference_download"])
        assert ctx.config_user["test_reference_download"] == {
            "_type": "artifactVersion",
            "_version": "v0",
            "id": artifact.id,
            "version": "v0",
            "sequenceName": artifact.name.split(":")[0],
            "usedAs": "test_reference_download",
        }


def test_wandb_artifact_config_update(
    runner, live_mock_server, test_settings, parse_ctx
):
    with runner.isolated_filesystem():
        open("file1.txt", "w").write("hello")
        artifact = wandb.Artifact("test_reference_download", "dataset")
        artifact.add_file("file1.txt")
        artifact.add_reference(
            "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
        )
        run = wandb.init(settings=test_settings)
        run.config.update({"test_reference_download": artifact})

        assert run.config.test_reference_download == artifact
        run.finish()

        ctx = parse_ctx(live_mock_server.get_ctx())
        print(ctx.config_user["test_reference_download"])
        assert ctx.config_user["test_reference_download"] == {
            "_type": "artifactVersion",
            "_version": "v0",
            "id": artifact.id,
            "version": "v0",
            "sequenceName": artifact.name.split(":")[0],
            "usedAs": "test_reference_download",
        }


def test_deprecated_feature_telemetry(live_mock_server, test_settings, parse_ctx):
    run = wandb.init(settings=test_settings)
    # use deprecated features
    deprecated_features = [
        run.mode,
        run.save(),
        run.join(),
    ]
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    telemetry = ctx_util.telemetry
    # TelemetryRecord field 10 is Deprecated,
    # whose fields 2-4 correspond to deprecated wandb.run features
    telemetry_deprecated = telemetry.get("10", [])
    assert (
        (2 in telemetry_deprecated)
        and (3 in telemetry_deprecated)
        and (4 in telemetry_deprecated)
    )
    run.finish()


# test that information about validation errors in wandb.Settings is included in telemetry
def test_settings_validation_telemetry(
    live_mock_server, test_settings, parse_ctx, capsys
):
    test_settings.update(api_key=123)
    captured = capsys.readouterr().err
    msg = "Invalid value for property api_key: 123"
    assert msg in captured
    run = wandb.init(settings=test_settings)
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    telemetry = ctx_util.telemetry
    # TelemetryRecord field 11 is Issues,
    # whose field 1 corresponds to validation warnings in Settings
    telemetry_issues = telemetry.get("11", [])
    assert 1 in telemetry_issues
    run.finish()


# test that information about validation errors in wandb.Settings is included in telemetry
def test_settings_preprocessing_telemetry(
    live_mock_server, test_settings, parse_ctx, capsys
):
    with mock.patch.dict("os.environ", WANDB_QUIET="cat"):
        run = wandb.init(settings=test_settings)
        captured = capsys.readouterr().err
        msg = "Unable to preprocess value for property quiet: cat"
        assert msg in captured and "This will raise an error in the future" in captured
        ctx_util = parse_ctx(live_mock_server.get_ctx())
        telemetry = ctx_util.telemetry
        # TelemetryRecord field 11 is Issues,
        # whose field 3 corresponds to preprocessing warnings in Settings
        telemetry_issues = telemetry.get("11", [])
        assert 3 in telemetry_issues
        run.finish()


def test_settings_unexpected_args_telemetry(
    runner, live_mock_server, parse_ctx, capsys
):
    with runner.isolated_filesystem():
        run = wandb.init(settings=wandb.Settings(blah=3))
        captured = capsys.readouterr().err
        msg = "Ignoring unexpected arguments: ['blah']"
        assert msg in captured
        ctx_util = parse_ctx(live_mock_server.get_ctx())
        telemetry = ctx_util.telemetry
        # TelemetryRecord field 11 is Issues,
        # whose field 2 corresponds to unexpected arguments in Settings
        telemetry_issues = telemetry.get("11", [])
        assert 2 in telemetry_issues
        run.finish()
