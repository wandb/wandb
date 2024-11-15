import math
import os
import pickle
import sys

import numpy as np
import pytest
import wandb
import wandb.env
from wandb.errors import UsageError


def test_log_nan_inf(wandb_backend_spy):
    with wandb.init() as run:
        run.log(
            {
                "nan": float("nan"),
                "inf": float("inf"),
                "nested": {"neg_inf": float("-inf")},
            }
        )

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)

        assert len(history) == 1
        assert math.isnan(history[0]["nan"])
        assert math.isinf(history[0]["inf"])
        assert math.isinf(history[0]["nested"]["neg_inf"])
        assert history[0]["nested"]["neg_inf"] < 0


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

    art = run.log_code(include_fn=lambda p: p.endswith((".py", ".cc")))
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
    run = wandb_init(settings=wandb.Settings(x_disable_stats=True))
    assert run.settings.x_disable_stats
    run.finish()


def test_attach_same_process(wandb_init, test_settings):
    with pytest.raises(RuntimeError) as excinfo:
        run = wandb_init(settings=test_settings())
        new_run = pickle.loads(pickle.dumps(run))
        new_run.log({"a": 2})
    run.finish()
    assert "attach in the same process is not supported" in str(excinfo.value)


def test_deprecated_feature_telemetry(wandb_backend_spy):
    with wandb.init(config_include_keys=["lol"]) as run:
        # use deprecated features
        _ = [
            run.mode,
            run.save(),
            run.join(),
        ]

    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run.id)

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
        (True, True),
        (None, False),
    ],
)
def test_offline_resume(wandb_init, test_settings, capsys, resume, found):
    run = wandb_init(mode="offline", resume=resume, settings=test_settings())
    captured = capsys.readouterr()
    assert assertion(run.id, found, captured.err)
    run.finish()


def test_ignore_globs_wandb_files(wandb_backend_spy):
    with wandb.init(settings=dict(ignore_globs=["requirements.txt"])) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        uploaded_files = snapshot.uploaded_files(run_id=run.id)
        assert "requirements.txt" not in uploaded_files


def test_network_fault_graphql(wandb_backend_spy):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.any(),
        # Fail every other request for 50 requests.
        gql.Sequence(
            [
                gql.Constant(content={"errors": ["Server down"]}, status=500),
                None,
            ]
            * 50,
        ),
    )

    with wandb.init() as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        uploaded_files = snapshot.uploaded_files(run_id=run.id)

        assert "wandb-metadata.json" in uploaded_files
        assert "wandb-summary.json" in uploaded_files
        assert "requirements.txt" in uploaded_files
        assert "config.yaml" in uploaded_files


def test_summary_update(wandb_backend_spy):
    with wandb.init() as run:
        run.summary.update({"a": 1})

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["a"] == 1


def test_summary_from_history(wandb_backend_spy):
    with wandb.init() as run:
        run.summary.update({"a": 1})
        run.log({"a": 2})

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["a"] == 2


@pytest.mark.wandb_core_only
def test_summary_remove(wandb_backend_spy):
    with wandb.init() as run:
        run.log({"a": 2})
        del run.summary["a"]

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert "a" not in summary


@pytest.mark.wandb_core_only
def test_summary_remove_nested(wandb_backend_spy):
    with wandb.init(allow_val_change=True) as run:
        run.log({"a": {"b": 2}})
        run.summary["a"]["c"] = 3
        del run.summary["a"]["b"]

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)
        assert summary["a"] == {"c": 3}


@pytest.mark.parametrize(
    "method, args",
    [
        ("alert", ["test", "test"]),
        ("define_metric", ["test"]),
        ("log", [{"test": 2}]),
        ("log_code", []),
        ("mark_preempting", []),
        ("save", []),
        ("status", []),
        ("link_artifact", [wandb.Artifact("test", type="dataset"), "input"]),
        ("use_artifact", ["test"]),
        ("log_artifact", ["test"]),
        ("upsert_artifact", ["test"]),
        ("finish_artifact", ["test"]),
    ],
)
def test_error_when_using_methods_of_finished_run(wandb_init, method, args):
    run = wandb_init()
    run.finish()

    with pytest.raises(wandb.errors.UsageError):
        getattr(run, method)(*args)


@pytest.mark.parametrize(
    "attribute, value",
    [
        ("config", ["test", 2]),
        ("summary", ["test", 2]),
        ("name", "test"),
        ("notes", "test"),
        ("tags", "test"),
    ],
)
def test_error_when_using_attributes_of_finished_run(wandb_init, attribute, value):
    run = wandb_init()
    run.finish()

    with pytest.raises(wandb.errors.UsageError):
        if isinstance(value, list):
            setattr(getattr(run, attribute), *value)
        else:
            setattr(run, attribute, value)
