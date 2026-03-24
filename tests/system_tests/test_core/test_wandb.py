"""Test the high level sdk methods by mocking out the backend.

See wandb_integration_test.py for tests that launch a real backend server.
"""

import glob
import io
import os
import platform
import tempfile
import unittest.mock
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
import requests
import wandb
from wandb.sdk.lib import filesystem


@pytest.fixture
def mock_sagemaker():
    config_path = "/opt/ml/input/config/hyperparameters.json"
    resource_path = "/opt/ml/input/config/resourceconfig.json"
    secrets_path = "secrets.env"

    orig_exist = os.path.exists

    def exists(path):
        if path in (config_path, secrets_path, resource_path):
            return True
        else:
            return orig_exist(path)

    def magic_factory(original):
        def magic(path, *args, **kwargs):
            if path == config_path:
                return io.StringIO('{"foo": "bar"}')
            elif path == resource_path:
                return io.StringIO('{"hosts":["a", "b"]}')
            elif path == secrets_path:
                return io.StringIO("WANDB_TEST_SECRET=TRUE")
            else:
                return original(path, *args, **kwargs)

        return magic

    with (
        unittest.mock.patch.dict(
            os.environ,
            {
                "TRAINING_JOB_NAME": "sage",
                "CURRENT_HOST": "maker",
            },
        ),
        unittest.mock.patch(
            "wandb.util.os.path.exists",
            exists,
        ),
        unittest.mock.patch(
            "builtins.open",
            magic_factory(open),
            create=True,
        ),
    ):
        yield


def test_sagemaker_key():
    with open("secrets.env", "w") as f:
        f.write("WANDB_API_KEY={}".format("S" * 40))
    assert wandb.api.api_key == "S" * 40


def test_sagemaker(user, git_repo, mock_sagemaker):
    run = wandb.init()
    run.finish()
    assert run.config.foo == "bar"
    assert run.id.startswith("sage-")
    assert run.id.endswith("-maker")
    assert run.group == "sage"
    # TODO: add test for secret, but for now there is no env or setting for it so its not added.
    # assert os.getenv("WANDB_TEST_SECRET") == "TRUE"


@pytest.mark.wandb_args(
    tf_config={
        "cluster": {"master": ["trainer-4dsl7-master-0:2222"]},
        "task": {"type": "master", "index": 0},
        "environment": "cloud",
    }
)
@pytest.mark.skip(
    reason="TF_CONFIG parsing not yet implemented, see wandb.util.parse_tfjob_config"
)
def test_simple_tfjob(user):
    run = wandb.init()
    run.finish()
    assert run.group is None
    assert run.job_type == "master"


@pytest.mark.wandb_args(
    tf_config={
        "cluster": {
            "master": ["trainer-sj2hp-master-0:2222"],
            "ps": ["trainer-sj2hp-ps-0:2222"],
            "worker": ["trainer-sj2hp-worker-0:2222"],
        },
        "task": {"type": "worker", "index": 0},
        "environment": "cloud",
    }
)
@pytest.mark.skip(
    reason="TF_CONFIG parsing not yet implemented, see wandb.util.parse_tfjob_config"
)
def test_distributed_tfjob(user):
    run = wandb.init()
    run.finish()
    assert run.group == "trainer-sj2hp"
    assert run.job_type == "worker"


@pytest.mark.wandb_args(tf_config={"cluster": {"corrupt": ["bad"]}})
@pytest.mark.skip(
    reason="TF_CONFIG parsing not yet implemented, see wandb.util.parse_tfjob_config"
)
def test_corrupt_tfjob(user):
    run = wandb.init()
    run.finish()
    assert run.group is None


@pytest.mark.wandb_args(env={"TF_CONFIG": "garbage"})
@pytest.mark.skip(
    reason="TF_CONFIG parsing not yet implemented, see wandb.util.parse_tfjob_config"
)
def test_bad_json_tfjob(user):
    run = wandb.init()
    run.finish()
    assert run.group is None


def test_custom_dir(user):
    with tempfile.TemporaryDirectory() as tmpdir:
        run = wandb.init(dir=tmpdir, mode="offline")
        run.finish()

        assert len(glob.glob(os.path.join(tmpdir, "wandb", "offline-*"))) > 0


def test_custom_dir_env(user):
    with mock.patch.dict("os.environ", {"WANDB_DIR": tempfile.gettempdir()}):
        run = wandb.init(mode="offline")
        run.finish()
        assert (
            len(glob.glob(os.path.join(tempfile.gettempdir(), "wandb", "offline-*")))
            > 0
        )


def test_run_id(user):
    with mock.patch.dict("os.environ", {"WANDB_RUN_ID": "123456"}):
        run = wandb.init()
        run.finish()
        assert run.id == "123456"


def test_run_name(user):
    with mock.patch.dict("os.environ", {"WANDB_NAME": "coolio"}):
        run = wandb.init()
        run.finish()
        assert run.name == "coolio"


def test_run_setname(user):
    with wandb.init() as run:
        run.name = "name1"
    assert run.name == "name1"


def test_run_notes(user):
    with mock.patch.dict("os.environ", {"WANDB_NOTES": "these are my notes"}):
        run = wandb.init()
        run.finish()
        assert run.notes == "these are my notes"


def test_run_setnotes(user):
    with wandb.init() as run:
        run.notes = "notes1"
    assert run.notes == "notes1"


def test_run_tags(user):
    with mock.patch.dict("os.environ", {"WANDB_TAGS": "tag1,tag2"}):
        run = wandb.init()
        run.finish()
        assert run.tags == ("tag1", "tag2")


def test_run_settags(user):
    with wandb.init() as run:
        run.tags = ("tag1", "tag2")
    assert run.tags == ("tag1", "tag2")


def test_run_offline(user):
    run = wandb.init(mode="offline")
    run.finish()
    assert run.offline is True


def test_run_entity(user):
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "ent1"}):
        run = wandb.init(mode="offline")
        run.finish()
        assert run.entity == "ent1"


def test_run_project(user):
    with mock.patch.dict("os.environ", {"WANDB_PROJECT": "proj1"}):
        run = wandb.init()
        run.finish()
        assert run.project == "proj1"
        assert run.project_name() == "proj1"


def test_run_group(user):
    with mock.patch.dict("os.environ", {"WANDB_RUN_GROUP": "group1"}):
        run = wandb.init()
        run.finish()
        assert run.group == "group1"


def test_run_jobtype(user):
    with mock.patch.dict("os.environ", {"WANDB_JOB_TYPE": "job1"}):
        run = wandb.init()
        run.finish()
        assert run.job_type == "job1"


def test_run_not_resumed(user):
    run = wandb.init()
    run.finish()
    assert run.resumed is False


def test_run_resumed(user):
    with wandb.init() as run:
        run.config.update({"fruit": "banana"})

    with wandb.init(id=run.id, resume="must") as run:
        assert run.resumed is True
        assert run.config.fruit == "banana"


def test_run_sweepid(user):
    run = wandb.init()
    run.finish()
    assert run.sweep_id is None


def test_run_configstatic(user):
    run = wandb.init()
    run.config.update(dict(this=2, that=3))
    assert dict(run.config_static) == dict(this=2, that=3)
    run.finish()


def test_run_path(user):
    with mock.patch.dict(
        "os.environ",
        {"WANDB_ENTITY": "ent1", "WANDB_PROJECT": "proj1", "WANDB_RUN_ID": "run1"},
    ):
        run = wandb.init(mode="offline")
        run.finish()
        assert run.path == "ent1/proj1/run1"


def test_run_create_root_dir(user, tmp_path):
    root_dir = tmp_path / "create_dir_test"

    with wandb.init(dir=root_dir) as run:
        run.log({"test": 1})

    assert os.path.exists(root_dir)


@pytest.mark.skipif(
    platform.system() == "Linux",
    reason=(
        "For tests run in CI on linux, the runas user is root. "
        "This means that the test can always write to the root dir, "
        "even if permissions are set to read only."
    ),
)
def test_run_create_root_dir_without_permissions_defaults_to_temp_dir(
    user,
    tmp_path,
):
    temp_dir = tempfile.gettempdir()
    root_dir = tmp_path / "no_permissions_test"
    root_dir.mkdir(parents=True, mode=0o444, exist_ok=True)

    with wandb.init(
        settings=wandb.Settings(root_dir=os.path.join(root_dir, "missing"))
    ) as run:
        run.log({"test": 1})

    assert not os.path.exists(os.path.join(root_dir, "missing"))
    assert run.settings.root_dir == temp_dir


def test_run_projecturl(user):
    run = wandb.init(settings={"mode": "offline"})
    run.finish()
    # URL is not available offline
    assert run.get_project_url() is None


def test_run_sweepurl(user):
    run = wandb.init(settings={"mode": "offline"})
    run.finish()
    # URL is not available offline
    assert run.get_sweep_url() is None


def test_run_url(user):
    run = wandb.init(settings={"mode": "offline"})
    run.finish()
    # URL is not available offline
    assert run.get_url() is None
    assert run.url is None


# ----------------------------------
# wandb.log
# ----------------------------------


def test_log_step(wandb_backend_spy):
    run = wandb.init()
    run.log({"acc": 1}, step=5, commit=True)
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert len(history) == 1
        assert history[0]["_step"] == 5


def test_log_custom_chart(wandb_backend_spy):
    run = wandb.init()
    my_custom_chart = wandb.plot_table(
        "test_spec", wandb.Table(data=[[1, 2], [3, 4]], columns=["A", "B"]), {}, {}
    )
    run.log({"my_custom_chart": my_custom_chart})
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert len(history) == 1
        assert history[0]["my_custom_chart_table"]


def test_log_silent(user, capsys):
    with mock.patch.dict("os.environ", {"WANDB_SILENT": "true"}):
        run = wandb.init()
        run.log({"acc": 1})
        run.finish()
    _, err = capsys.readouterr()
    assert "wandb: " not in err


def test_log_multiple_cases_example(wandb_backend_spy):
    run = wandb.init()
    run.log(dict(n=1))
    run.log(dict(n=11), commit=False)
    run.log(dict(n=2), step=100)
    run.log(dict(n=3), step=100)
    run.log(dict(n=8), step=101)
    run.log(dict(n=5), step=102)
    run.log(dict(cool=2), step=2)
    run.log(dict(cool=2), step=4)
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert [value["n"] for value in history.values()] == [1, 11, 3, 8, 5]
        assert [value["_step"] for value in history.values()] == [0, 1, 100, 101, 102]


def test_log_step_uncommitted(wandb_backend_spy):
    run = wandb.init()
    run.log(dict(cool=2), step=2, commit=False)
    run.log(dict(cool=2), step=4)
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert len(history) == 2


def test_log_step_committed(wandb_backend_spy):
    run = wandb.init()
    run.log(dict(cool=2), step=2)
    run.log(dict(cool=2), step=4, commit=True)
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert len(history) == 2


def test_log_step_committed_same(wandb_backend_spy):
    run = wandb.init()
    run.log(dict(cool=2), step=1)
    run.log(dict(cool=2), step=4)
    run.log(dict(bad=3), step=4, commit=True)
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)

        assert len(history) == 2
        assert history[0]["cool"] == 2

        assert history[1]["bad"] == 3
        assert history[1]["cool"] == 2


def test_log_step_committed_same_dropped(wandb_backend_spy):
    run = wandb.init()
    run.log(dict(cool=2), step=1)
    run.log(dict(cool=2), step=4, commit=True)
    run.log(dict(bad=3), step=4, commit=True)
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert len(history) == 2
        assert history[0]["_step"] == 1
        assert history[0]["cool"] == 2

        assert history[1]["_step"] == 4
        assert "bad" not in history[1]

        # filter all the columns that don't start with `_`
        for value in history.values():
            items = [k for k in value if not k.startswith("_")]
            assert len(items) == 1


def test_log_empty_string(wandb_backend_spy):
    run = wandb.init()
    run.log(dict(cool=""))
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert history[0]["cool"] == ""


def test_log_table_offline_no_network(user, monkeypatch):
    num_network_calls_made = 0
    original_request = requests.Session.request

    def mock_request(self, *args, **kwargs):
        nonlocal num_network_calls_made
        num_network_calls_made += 1
        return original_request(self, *args, **kwargs)

    monkeypatch.setattr(requests.Session, "request", mock_request)
    run = wandb.init(mode="offline")
    run.log({"table": wandb.Table()})
    run.finish()
    assert num_network_calls_made == 0
    assert run.offline is True


def test_log_with_glob_chars(user, wandb_backend_spy):
    run = wandb.init()
    run.log({"[glob chars]": wandb.Image(np.random.randint(0, 255, (100, 100, 3)))})
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        uploaded_files = snapshot.uploaded_files(run_id=run.id)
        assert any("[glob chars]" in f for f in uploaded_files)


# ----------------------------------
# wandb.save
# ----------------------------------


@pytest.mark.xfail(reason="This test is flaky")
def test_save_invalid_path(user):
    run = wandb.init()
    root = tempfile.gettempdir()
    test_path = os.path.join(root, "tmp", "test.txt")
    filesystem.mkdir_exists_ok(os.path.dirname(test_path))
    with open(test_path, "w") as f:
        f.write("something")
    with pytest.raises(ValueError):
        run.save(os.path.join(root, os.pardir, os.pardir, "*.txt"), base_path=root)
    run.finish()


# ----------------------------------
# wandb.restore
# ----------------------------------


@pytest.fixture
def create_run_with_file(user):
    @contextmanager
    def create_file_for_run_fn(file_name, file_content):
        run = wandb.init(settings={"save_code": True})
        try:
            file = Path(run.dir) / file_name
            file.touch(exist_ok=True)
            file.write_text(file_content)
            yield run, file
        finally:
            run.finish()
            file.unlink()

    return create_file_for_run_fn


def test_restore_no_path():
    with pytest.raises(ValueError, match="run_path required"):
        wandb.restore("weights.h5")


@pytest.mark.skip(reason="This test seems to be flaky")
def test_restore_name_not_found(user):
    with pytest.raises(ValueError):
        run = wandb.init()
        run.restore("no_file.h5")


@pytest.mark.xfail(reason="Public API might not return the correct value")
def test_restore_no_init(create_run_with_file):
    with create_run_with_file("weights.h5", "content") as (run, file):
        file_size = os.path.getsize(file)

    res = wandb.restore("weights.h5", run_path=run.path)
    assert os.path.getsize(res.name) == file_size


@pytest.mark.xfail(reason="Public API might not return the correct value")
def test_restore(create_run_with_file, test_settings):
    with create_run_with_file("weights.h5", "content") as (run, file):
        file_size = os.path.getsize(file)

    with wandb.init(settings=test_settings()):
        res = wandb.restore("weights.h5", run_path=run.path)
        assert os.path.getsize(res.name) == file_size


# ----------------------------------
# wandb.attach
# ----------------------------------


def test_attach_usage_errors(user):
    run = wandb.init()
    with pytest.raises(wandb.UsageError) as e:
        wandb._attach()
    assert "Either (`attach_id` or `run_id`) or `run` must be specified" in str(e.value)
    run.finish()


# TODO: test these or make sure they are tested somewhere
# run.use_artifact()
# run.log_artifact()
