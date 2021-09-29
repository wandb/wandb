"""
config tests.
"""

import os
import sys
import numpy as np
import platform
import pytest

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
    test_settings.save_code = True
    test_settings.code_dir = "."
    run = wandb.init(settings=test_settings)
    run.finish()
    ctx = live_mock_server.get_ctx()
    artifact_name = list(ctx["artifacts"].keys())[0]
    assert artifact_name == "source-" + run.id


def test_log_code(test_settings):
    run = wandb.init(mode="offline", settings=test_settings)
    with open("test.py", "w") as f:
        f.write('print("test")')
    with open("big_file.h5", "w") as f:
        f.write("Not that big")
    art = run.log_code()
    assert sorted(art.manifest.entries.keys()) == ["test.py"]


def test_log_code_include(test_settings):
    run = wandb.init(mode="offline", settings=test_settings)
    with open("test.py", "w") as f:
        f.write('print("test")')
    with open("test.cc", "w") as f:
        f.write("Not that big")
    art = run.log_code(include_fn=lambda p: p.endswith(".py") or p.endswith(".cc"))
    assert sorted(art.manifest.entries.keys()) == ["test.cc", "test.py"]


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


def test_display(test_settings):
    run = wandb.init(mode="offline", settings=test_settings)
    assert run.display() == False


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


def assertion(run_id, found, stderr):
    msg = f"`resume` will be ignored since W&B syncing is set to `offline`. Starting a new run with run id {run_id}"
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
        (None, False),
    ],
)
def test_offline_resume(test_settings, capsys, resume, found):
    run = wandb.init(mode="offline", resume=resume, settings=test_settings)
    captured = capsys.readouterr()
    assert assertion(run.id, found, captured.err)


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


def test_use_artifact_offline(live_mock_server, test_settings):
    run = wandb.init(mode="offline")
    with pytest.raises(Exception) as e_info:
        artifact = run.use_artifact("boom-data")
        assert str(e_info.value) == "Cannot use artifact when in offline mode."


@pytest.mark.parametrize("project_name", ["test:?", "test" * 33])
def test_invalid_project_name(live_mock_server, project_name):
    with pytest.raises(UsageError) as e:
        _ = wandb.init(project=project_name)
        assert 'Invalid project name "{project_name}"' in str(e.value)
