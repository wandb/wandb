"""These test the high level sdk methods by mocking out the backend.
See wandb_integration_test.py for tests that launch a real backend against
a live backend server.
"""
import glob
import inspect
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest
import wandb
from wandb.sdk.wandb_init import init as real_wandb_init
from wandb.viz import custom_chart


def test_wandb_init_fixture_args(wandb_init):
    """Test that the fixture args are in sync with the real wandb.init()."""
    # comparing lists of args as order also matters
    assert (
        inspect.getfullargspec(real_wandb_init).args
        == inspect.getfullargspec(wandb_init).args
    )


def test_sagemaker_key():
    with open("secrets.env", "w") as f:
        f.write("WANDB_API_KEY={}".format("S" * 40))
    assert wandb.api.api_key == "S" * 40


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
def test_simple_tfjob(wandb_init):
    assert wandb.run.group is None
    assert wandb.run.job_type == "master"


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
def test_distributed_tfjob(wandb_init):
    assert wandb.run.group == "trainer-sj2hp"
    assert wandb.run.job_type == "worker"


@pytest.mark.wandb_args(tf_config={"cluster": {"corrupt": ["bad"]}})
@pytest.mark.skip(
    reason="TF_CONFIG parsing not yet implemented, see wandb.util.parse_tfjob_config"
)
def test_corrupt_tfjob(wandb_init):
    assert wandb.run.group is None


@pytest.mark.wandb_args(env={"TF_CONFIG": "garbage"})
@pytest.mark.skip(
    reason="TF_CONFIG parsing not yet implemented, see wandb.util.parse_tfjob_config"
)
def test_bad_json_tfjob(wandb_init):
    assert wandb.run.group is None


def test_custom_dir(wandb_init):
    with tempfile.TemporaryDirectory() as tmpdir:
        run = wandb_init(dir=tmpdir, mode="offline")
        run.finish()

        assert len(glob.glob(os.path.join(tmpdir, "wandb", "offline-*"))) > 0


def test_custom_dir_env(wandb_init):
    with mock.patch.dict("os.environ", {"WANDB_DIR": tempfile.gettempdir()}):
        run = wandb_init(mode="offline")
        run.finish()
    assert len(glob.glob(os.path.join(tempfile.gettempdir(), "wandb", "offline-*"))) > 0


@pytest.mark.xfail(reason="Backend race condition")
def test_anonymous_mode(wandb_init, capsys, local_settings):
    copied_env = os.environ.copy()
    copied_env.pop("WANDB_API_KEY")
    copied_env.pop("WANDB_USERNAME")
    copied_env.pop("WANDB_ENTITY")
    with mock.patch.dict("os.environ", copied_env, clear=True):
        run = wandb_init(anonymous="must")
        run.log({"something": 1})
        run.finish()

    _, err = capsys.readouterr()
    assert (
        "Do NOT share these links with anyone. They can be used to claim your runs."
        in err
    )


@pytest.mark.xfail(reason="Backend race condition")
def test_anonymous_mode_artifact(wandb_init, capsys, local_settings):
    copied_env = os.environ.copy()
    copied_env.pop("WANDB_API_KEY")
    copied_env.pop("WANDB_USERNAME")
    copied_env.pop("WANDB_ENTITY")
    with mock.patch.dict("os.environ", copied_env, clear=True):

        run = wandb_init(anonymous="must")
        run.log_artifact(wandb.Artifact("my-arti", type="dataset"))
        run.finish()

    _, err = capsys.readouterr()

    assert (
        "Artifacts logged anonymously cannot be claimed and expire after 7 days." in err
    )


def test_run_id(wandb_init):
    with mock.patch.dict("os.environ", {"WANDB_RUN_ID": "123456"}):
        run = wandb_init()
        run.finish()
        assert run.id == "123456"


def test_run_name(wandb_init):
    with mock.patch.dict("os.environ", {"WANDB_NAME": "coolio"}):
        run = wandb_init()
        run.finish()
        assert run.name == "coolio"


def test_run_setname(wandb_init):
    run = wandb_init()
    run.name = "name1"
    run.finish()
    assert run.name == "name1"


def test_run_notes(wandb_init):
    with mock.patch.dict("os.environ", {"WANDB_NOTES": "these are my notes"}):
        run = wandb_init()
        run.finish()
        assert run.notes == "these are my notes"


def test_run_setnotes(wandb_init):
    run = wandb_init()
    run.notes = "notes1"
    run.finish()
    assert run.notes == "notes1"


def test_run_tags(wandb_init):
    with mock.patch.dict("os.environ", {"WANDB_TAGS": "tag1,tag2"}):
        run = wandb_init()
        run.finish()
        assert run.tags == ("tag1", "tag2")


def test_run_settags(wandb_init):
    run = wandb_init()
    run.tags = ("tag1", "tag2")
    run.finish()
    assert run.tags == ("tag1", "tag2")


def test_run_mode(wandb_init):
    run = wandb_init(mode="dryrun")
    run.finish()
    assert run.mode == "dryrun"


def test_run_offline(wandb_init):
    run = wandb_init(mode="offline")
    run.finish()
    assert run.offline is True


def test_run_entity(wandb_init):
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "ent1"}):
        run = wandb_init(mode="offline")
        run.finish()
        assert run.entity == "ent1"


def test_run_project(wandb_init):
    with mock.patch.dict("os.environ", {"WANDB_PROJECT": "proj1"}):
        run = wandb_init()
        run.finish()
        assert run.project == "proj1"
        assert run.project_name() == "proj1"


def test_run_group(wandb_init):
    with mock.patch.dict("os.environ", {"WANDB_RUN_GROUP": "group1"}):
        run = wandb_init()
        run.finish()
        assert run.group == "group1"


def test_run_jobtype(wandb_init):
    with mock.patch.dict("os.environ", {"WANDB_JOB_TYPE": "job1"}):
        run = wandb_init()
        run.finish()
        assert run.job_type == "job1"


def test_run_resumed(wandb_init):
    run = wandb_init()
    run.finish()
    assert run.resumed is False


def test_run_sweepid(wandb_init):
    run = wandb_init()
    run.finish()
    assert run.sweep_id is None


def test_run_configstatic(wandb_init):
    run = wandb_init()
    run.config.update(dict(this=2, that=3))
    assert dict(run.config_static) == dict(this=2, that=3)
    run.finish()


def test_run_path(wandb_init):
    with mock.patch.dict(
        "os.environ",
        {"WANDB_ENTITY": "ent1", "WANDB_PROJECT": "proj1", "WANDB_RUN_ID": "run1"},
    ):
        run = wandb_init(mode="offline")
        run.finish()
        assert run.path == "ent1/proj1/run1"


def test_run_projecturl(wandb_init):
    run = wandb_init(settings={"mode": "offline"})
    run.finish()
    # URL is not available offline
    assert run.get_project_url() is None


def test_run_sweepurl(wandb_init):
    run = wandb_init(settings={"mode": "offline"})
    run.finish()
    # URL is not available offline
    assert run.get_sweep_url() is None


def test_run_url(wandb_init):
    run = wandb_init(settings={"mode": "offline"})
    run.finish()
    # URL is not available offline
    assert run.get_url() is None
    assert run.url is None


# ----------------------------------
# wandb.log
# ----------------------------------


def test_nice_log_error():
    with pytest.raises(wandb.Error):
        wandb.log({"no": "init"})


def test_nice_log_error_config():
    with pytest.raises(
        wandb.Error, match=r"You must call wandb.init\(\) before wandb.config.update"
    ):
        wandb.config.update({"foo": 1})
    with pytest.raises(
        wandb.Error, match=r"You must call wandb.init\(\) before wandb.config.foo"
    ):
        wandb.config.foo = 1


def test_nice_log_error_summary():
    with pytest.raises(
        wandb.Error,
        match=r'You must call wandb.init\(\) before wandb.summary\["great"\]',
    ):
        wandb.summary["great"] = 1
    with pytest.raises(
        wandb.Error, match=r"You must call wandb.init\(\) before wandb.summary.bam"
    ):
        wandb.summary.bam = 1


def test_log_only_strings_as_keys(mock_run):
    run = mock_run()
    with pytest.raises(ValueError):
        run.log({1: 1000})
    with pytest.raises(ValueError):
        run.log({("tup", "idx"): 1000})


def test_log_not_dict(mock_run):
    run = mock_run()
    with pytest.raises(ValueError):
        run.log(10)


def test_log_step(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.log({"acc": 1}, step=5, commit=True)
        run.finish()
    assert relay.context.history["_step"][0] == 5


def test_log_custom_chart(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        my_custom_chart = custom_chart(
            "test_spec", wandb.Table(data=[[1, 2], [3, 4]], columns=["A", "B"]), {}, {}
        )
        run.log({"my_custom_chart": my_custom_chart})
        run.finish()

    assert relay.context.history["my_custom_chart_table"][0]


def test_log_silent(wandb_init, capsys):
    with mock.patch.dict("os.environ", {"WANDB_SILENT": "true"}):
        run = wandb_init()
        run.log({"acc": 1})
        run.finish()
    _, err = capsys.readouterr()
    assert "wandb: " not in err


def test_log_multiple_cases_example(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.log(dict(n=1))
        run.log(dict(n=11), commit=False)
        run.log(dict(n=2), step=100)
        run.log(dict(n=3), step=100)
        run.log(dict(n=8), step=101)
        run.log(dict(n=5), step=102)
        run.log(dict(cool=2), step=2)
        run.log(dict(cool=2), step=4)
        run.finish()

    assert relay.context.history["n"].tolist() == [1, 11, 3, 8, 5]
    assert relay.context.history["_step"].tolist() == [0, 1, 100, 101, 102]


def test_log_step_uncommited(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.log(dict(cool=2), step=2, commit=False)
        run.log(dict(cool=2), step=4)
        run.finish()

    assert len(relay.context.history) == 2


def test_log_step_committed(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.log(dict(cool=2), step=2)
        run.log(dict(cool=2), step=4, commit=True)
        run.finish()

    assert len(relay.context.history) == 2


def test_log_step_committed_same(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.log(dict(cool=2), step=1)
        run.log(dict(cool=2), step=4)
        run.log(dict(bad=3), step=4, commit=True)
        run.finish()

    history = relay.context.get_run_history(run.id)
    assert len(history) == 2
    assert history.cool[1] == 2
    assert history.bad[1] == 3
    assert len(history.columns) == 2


def test_log_step_committed_same_dropped(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.log(dict(cool=2), step=1)
        run.log(dict(cool=2), step=4, commit=True)
        run.log(dict(bad=3), step=4, commit=True)
        run.finish()

    history = relay.context.get_run_history(run.id)
    assert len(history) == 2
    assert history["cool"][1] == 2
    # filter all the columns that don't start with `_`
    assert len(history.columns) == 1


# ----------------------------------
# wandb.save
# ----------------------------------


@pytest.mark.xfail(reason="This test is flaky")
def test_save_invalid_path(wandb_init):
    run = wandb_init()
    root = tempfile.gettempdir()
    test_path = os.path.join(root, "tmp", "test.txt")
    wandb.util.mkdir_exists_ok(os.path.dirname(test_path))
    with open(test_path, "w") as f:
        f.write("something")
    with pytest.raises(ValueError):
        run.save(os.path.join(root, os.pardir, os.pardir, "*.txt"), base_path=root)
    run.finish()


@pytest.mark.xfail(reason="This test is flaky")
def test_save_policy_symlink(mock_run, parse_records, record_q):
    run = mock_run()

    with open("test.rad", "w") as f:
        f.write("something")
    run.save("test.rad")
    assert os.path.exists(os.path.join(run.dir, "test.rad"))
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "test.rad"
    assert file_record.policy == 2


@pytest.mark.xfail(reason="This test is flaky")
def test_save_policy_glob_symlink(mock_run, parse_records, record_q, capsys):
    run = mock_run()

    with open("test.rad", "w") as f:
        f.write("something")
    with open("foo.rad", "w") as f:
        f.write("something")
    run.save("*.rad")
    _, err = capsys.readouterr()
    assert "Symlinked 2 files" in err
    assert os.path.exists(os.path.join(run.dir, "test.rad"))
    assert os.path.exists(os.path.join(run.dir, "foo.rad"))

    # test_save_policy_glob_symlink
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "*.rad"
    assert file_record.policy == 2


@pytest.mark.xfail(reason="This test is flaky")
def test_save_absolute_path(mock_run, parse_records, record_q, capsys):
    run = mock_run()
    root = tempfile.gettempdir()
    test_path = os.path.join(root, "test.txt")
    with open(test_path, "w") as f:
        f.write("something")

    run.save(test_path)
    _, err = capsys.readouterr()
    assert "Saving files without folders" in err
    assert os.path.exists(os.path.join(run.dir, "test.txt"))
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == "test.txt"
    assert file_record.policy == 2


@pytest.mark.xfail(reason="This test is flaky")
def test_save_relative_path(mock_run, parse_records, record_q):
    run = mock_run()
    root = tempfile.gettempdir()
    test_path = os.path.join(root, "tmp", "test.txt")
    print("DAMN", os.path.dirname(test_path))
    wandb.util.mkdir_exists_ok(os.path.dirname(test_path))
    with open(test_path, "w") as f:
        f.write("something")
    run.save(test_path, base_path=root, policy="now")
    assert os.path.exists(os.path.join(run.dir, test_path))
    parsed = parse_records(record_q)
    file_record = parsed.files[0].files[0]
    assert file_record.path == os.path.relpath(test_path, root)
    assert file_record.policy == 0


# ----------------------------------
# wandb.restore
# ----------------------------------


@pytest.fixture
def create_run_with_file(wandb_init):
    @contextmanager
    def create_file_for_run_fn(file_name, file_content):
        run = wandb_init(settings={"save_code": True})
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


@pytest.mark.xfail(reason="Public API might not return the correct value")
def test_restore_name_not_found(wandb_init):
    with pytest.raises(ValueError):
        run = wandb_init()
        wandb.restore("no_file.h5")
        run.finish()


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


def test_attach_usage_errors(wandb_init):
    run = wandb_init()
    if not os.environ.get("WANDB_REQUIRE_SERVICE"):

        with pytest.raises(wandb.UsageError) as e:
            wandb._attach(run=run)
        assert (
            "Either `attach_id` or `run_id` must be specified or `run` must have `_attach_id`"
            in str(e.value)
        )

    with pytest.raises(wandb.UsageError) as e:
        wandb._attach()
    assert "Either (`attach_id` or `run_id`) or `run` must be specified" in str(e.value)
    run.finish()


# ----------------------------------
# wandb.teardown
# ----------------------------------

# In a notebook environment we might get into a situation where the service process will be removed
# but the singleton setup instance still exists, hence it will try to do the teardown.
# Howeverwandb.teardown will encounter an error because the service process is already gone.
# but since we have an error handle logic in the teardown, we don't see the error
# only informational message about the error.
def test_teardown_error_path(capsys):
    with mock.patch.dict(
        os.environ, {wandb.env.SERVICE: "2-96604-tcp-localhost-57337"}
    ):
        with mock.patch.object(
            wandb.sdk.wandb_manager._Manager,
            "_get_service_interface",
            return_value=mock.MagicMock(),
        ):
            wandb.setup()
        assert wandb.wandb_sdk.wandb_setup._WandbSetup._instance
        wandb.teardown()
        assert wandb.env.SERVICE not in os.environ
        assert not wandb.wandb_sdk.wandb_setup._WandbSetup._instance
    _, err = capsys.readouterr()
    assert (
        "While tearing down the service manager. The following error has occured:"
        in err
    )


# TODO: test these or make sure they are tested somewhere
# run.use_artifact()
# run.log_artifact()
