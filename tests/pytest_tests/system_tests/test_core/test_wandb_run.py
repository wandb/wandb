import json
import os
import pickle
import sys

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
def test_invalid_project_name(wandb_init, project_name):
    with pytest.raises(UsageError) as e:
        wandb_init(project=project_name)
        assert 'Invalid project name "{project_name}"' in str(e.value)


def test_resume_must_failure(wandb_init):
    with pytest.raises(wandb.UsageError):
        wandb_init(reinit=True, resume="must")


def test_unlogged_artifact_in_config(wandb_init, test_settings):
    run = wandb_init(settings=test_settings())
    artifact = wandb.Artifact("my-arti", type="dataset")
    with pytest.raises(Exception) as e_info:
        run.config.dataset = artifact
        assert (
            str(e_info.value)
            == "Cannot json encode artifact before it has been logged or in offline mode."
        )
    run.finish()


def test_media_in_config(runner, wandb_init, test_settings):
    with runner.isolated_filesystem():
        run = wandb_init(settings=test_settings())
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


def test_attach_same_process(wandb_init, test_settings):
    with pytest.raises(RuntimeError) as excinfo:
        run = wandb_init(settings=test_settings())
        new_run = pickle.loads(pickle.dumps(run))
        new_run.log({"a": 2})
    run.finish()
    assert "attach in the same process is not supported" in str(excinfo.value)


def test_deprecated_feature_telemetry(wandb_init, relay_server, test_settings, user):
    with relay_server() as relay:
        run = wandb_init(
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


def test_except_hook(wandb_init, test_settings):
    # Test to make sure we respect excepthooks by 3rd parties like pdb
    errs = []

    def hook(etype, val, tb):
        return errs.append(str(val))

    sys.excepthook = hook

    # We cant use raise statement in pytest context
    def raise_(exc):
        return sys.excepthook(type(exc), exc, None)

    raise_(Exception("Before wandb.init()"))

    run = wandb_init(mode="offline", settings=test_settings())

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
        (True, True),
        (None, False),
    ],
)
def test_offline_resume(wandb_init, test_settings, capsys, resume, found):
    run = wandb_init(mode="offline", resume=resume, settings=test_settings())
    captured = capsys.readouterr()
    assert assertion(run.id, found, captured.err)
    run.finish()


@pytest.mark.parametrize(
    "local_info, warn",
    [
        (
            {
                "outOfDate": True,
                "latestVersionString": "12.0.0",
            },
            True,
        ),
        (
            {
                "outOfDate": False,
                "latestVersionString": "12.0.0",
            },
            False,
        ),
        (None, False),
        ({}, True),
    ],
)
@pytest.mark.wandb_core_failure(
    feature="version_check",
    reason="need to implement versioning in wandb core",
)
def test_local_warning(
    relay_server,
    inject_graphql_response,
    wandb_init,
    capsys,
    local_info,
    warn,
):
    body = {
        "viewer": {},
        "serverInfo": {"cliVersionInfo": {}},
    }
    if local_info != "":
        body["serverInfo"]["latestLocalVersionInfo"] = local_info

    inject_response = inject_graphql_response(
        body=json.dumps({"data": body}),
        status=200,
        query_match_fn=lambda query, _: "query Viewer" in query,
        application_pattern="1",
    )
    # we do not retry 409s on queries, so this should fail
    with relay_server(inject=[inject_response]):
        run = wandb_init()
        run.finish()
    captured = capsys.readouterr().err

    msg = "version of W&B Server to get the latest features"
    if warn:
        assert msg in captured
    else:
        assert msg not in captured


@pytest.mark.wandb_core_failure(
    feature="file_uploader",
    reason="need to implement upload of wandb files",
)
def test_network_fault_graphql(relay_server, inject_graphql_response, wandb_init):
    inject_response = inject_graphql_response(
        body=json.dumps({"errors": ["Server down"]}),
        status=500,
        query_match_fn=lambda *_: True,
        application_pattern="1" * 5 + "2",  # apply once and stop
    )
    with relay_server(inject=[inject_response]) as relay:
        run = wandb_init()
        run.finish()

        uploaded_files = relay.context.get_run_uploaded_files(run.id)

        assert "wandb-metadata.json" in uploaded_files
        assert "wandb-summary.json" in uploaded_files
        assert "requirements.txt" in uploaded_files
        assert "config.yaml" in uploaded_files
