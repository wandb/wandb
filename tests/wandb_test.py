"""These test the high level sdk methods by mocking out the backend.
See wandb_integration_test.py for tests that launch a real backend against
a live backend server.
"""
import wandb
from wandb.viz import create_custom_chart
import pytest
import tempfile
import glob
import os
import sys


def test_log_step(wandb_init_run):
    wandb.log({"acc": 1}, step=5, commit=True)
    assert wandb.run._backend.history[0]["_step"] == 5


def test_log_custom_chart(wandb_init_run):
    custom_chart = create_custom_chart(
        "test_spec", wandb.Table(data=[[1, 2], [3, 4]], columns=["A", "B"]), {}, {}
    )
    wandb.log({"my_custom_chart": custom_chart})
    assert wandb.run._backend.history[0].get("my_custom_chart_table")


@pytest.mark.wandb_args({"env": {"WANDB_SILENT": "true"}})
@pytest.mark.skip(reason="We haven't implemented wandb silent yet")
def test_log_silent(wandb_init_run, capsys):
    wandb.log({"acc": 1})
    _, err = capsys.readouterr()
    assert "wandb: " not in err


def test_log_only_strings_as_keys(wandb_init_run):
    with pytest.raises(ValueError):
        wandb.log({1: 1000})
    with pytest.raises(ValueError):
        wandb.log({("tup", "idx"): 1000})


def test_log_not_dict(wandb_init_run):
    with pytest.raises(ValueError):
        wandb.log(10)


def test_log_step_uncommited(wandb_init_run):
    wandb.log(dict(cool=2), step=2)
    wandb.log(dict(cool=2), step=4)
    assert len(wandb.run._backend.history) == 1


def test_log_step_committed(wandb_init_run):
    wandb.log(dict(cool=2), step=2)
    wandb.log(dict(cool=2), step=4, commit=True)
    assert len(wandb.run._backend.history) == 2


def test_log_step_committed_same(wandb_init_run):
    wandb.log(dict(cool=2), step=1)
    wandb.log(dict(cool=2), step=4)
    wandb.log(dict(bad=3), step=4, commit=True)
    assert len(wandb.run._backend.history) == 2
    assert (
        len([x for x in wandb.run._backend.history[-1].keys() if not x.startswith("_")])
        == 2
    )
    assert wandb.run._backend.history[-1]["cool"] == 2
    assert wandb.run._backend.history[-1]["bad"] == 3


def test_log_step_committed_same_dropped(wandb_init_run):
    wandb.log(dict(cool=2), step=1)
    wandb.log(dict(cool=2), step=4, commit=True)
    wandb.log(dict(bad=3), step=4, commit=True)
    assert len(wandb.run._backend.history) == 2
    assert (
        len([x for x in wandb.run._backend.history[-1].keys() if not x.startswith("_")])
        == 1
    )
    assert wandb.run._backend.history[-1]["cool"] == 2


def test_nice_log_error():
    with pytest.raises(wandb.Error):
        wandb.log({"no": "init"})


def test_nice_log_error_config():
    with pytest.raises(wandb.Error) as e:
        wandb.config.update({"foo": 1})
    assert e.value.message == "You must call wandb.init() before wandb.config.update"
    with pytest.raises(wandb.Error) as e:
        wandb.config.foo = 1
    assert e.value.message == "You must call wandb.init() before wandb.config.foo"


def test_nice_log_error_summary():
    with pytest.raises(wandb.Error) as e:
        wandb.summary["great"] = 1
    assert e.value.message == 'You must call wandb.init() before wandb.summary["great"]'
    with pytest.raises(wandb.Error) as e:
        wandb.summary.bam = 1
    assert e.value.message == "You must call wandb.init() before wandb.summary.bam"


@pytest.mark.wandb_args(k8s=True)
def test_k8s_success(wandb_init_run):
    assert wandb.run._settings.docker == "test@sha256:1234"


@pytest.mark.wandb_args(k8s=False)
def test_k8s_failure(wandb_init_run):
    assert wandb.run._settings.docker is None


@pytest.mark.wandb_args(sagemaker=True)
@pytest.mark.skipif(
    sys.version_info < (3, 0), reason="py27 patch doesn't work with builtins"
)
def test_sagemaker(wandb_init_run):
    assert wandb.config.fuckin == "A"
    assert wandb.run.id == "sage-maker"
    # TODO: add test for secret, but for now there is no env or setting for it
    #  so its not added. Similarly add test for group
    # assert os.getenv("WANDB_TEST_SECRET") == "TRUE"
    # assert wandb.run.group == "sage"


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
def test_simple_tfjob(wandb_init_run):
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
def test_distributed_tfjob(wandb_init_run):
    assert wandb.run.group == "trainer-sj2hp"
    assert wandb.run.job_type == "worker"


@pytest.mark.wandb_args(tf_config={"cluster": {"corrupt": ["bad"]}})
@pytest.mark.skip(
    reason="TF_CONFIG parsing not yet implemented, see wandb.util.parse_tfjob_config"
)
def test_corrupt_tfjob(wandb_init_run):
    assert wandb.run.group is None


@pytest.mark.wandb_args(env={"TF_CONFIG": "garbage"})
@pytest.mark.skip(
    reason="TF_CONFIG parsing not yet implemented, see wandb.util.parse_tfjob_config"
)
def test_bad_json_tfjob(wandb_init_run):
    assert wandb.run.group is None


@pytest.mark.wandb_args(wandb_init={"dir": "/tmp"})
def test_custom_dir(wandb_init_run):
    assert len(glob.glob("/tmp/wandb/offline-*")) > 0


@pytest.mark.wandb_args(env={"WANDB_DIR": "/tmp"})
def test_custom_dir_env(wandb_init_run):
    assert len(glob.glob("/tmp/wandb/offline-*")) > 0


def test_login_key(capsys):
    wandb.login(key="A" * 40)
    # TODO: this was a bug when tests were leaking out to the global config
    # wandb.api.set_setting("base_url", "http://localhost:8080")
    out, err = capsys.readouterr()
    print(out)
    print(err)
    assert "Appending key" in err
    #  WTF is happening?
    assert wandb.api.api_key == "A" * 40


def test_sagemaker_key(runner):
    with runner.isolated_filesystem():
        with open("secrets.env", "w") as f:
            f.write("WANDB_API_KEY={}".format("S" * 40))
        assert wandb.api.api_key == "S" * 40


@pytest.mark.skip(reason="We dont validate keys in wandb.login() right now")
def test_login_invalid_key():
    os.environ["WANDB_API_KEY"] = "B" * 40
    wandb.ensure_configured()
    with pytest.raises(wandb.UsageError):
        wandb.login()
    del os.environ["WANDB_API_KEY"]


@pytest.mark.skip(reason="This doesn't work for some reason")
def test_login_anonymous(mock_server, local_netrc):
    os.environ["WANDB_API_KEY"] = "B" * 40
    wandb.login(anonymous="must")
    assert wandb.api.api_key == "ANONYMOOSE" * 4


def test_login_sets_api_base_url(mock_server):
    base_url = "https://api.test.host.ai"
    wandb.login(anonymous="must", host=base_url)
    api = wandb.Api()
    assert api.settings["base_url"] == base_url
    base_url = "https://api.wandb.ai"
    wandb.login(anonymous="must", host=base_url)
    api = wandb.Api()
    assert api.settings["base_url"] == base_url


def test_save_policy_symlink(wandb_init_run):
    with open("test.rad", "w") as f:
        f.write("something")
    wandb.save("test.rad")
    assert os.path.exists(os.path.join(wandb_init_run.dir, "test.rad"))
    assert wandb.run._backend.files["test.rad"] == 2


def test_save_policy_glob_symlink(wandb_init_run, capsys):
    with open("test.rad", "w") as f:
        f.write("something")
    with open("foo.rad", "w") as f:
        f.write("something")
    wandb.save("*.rad")
    _, err = capsys.readouterr()
    assert "Symlinked 2 files" in err
    assert os.path.exists(os.path.join(wandb_init_run.dir, "test.rad"))
    assert os.path.exists(os.path.join(wandb_init_run.dir, "foo.rad"))
    assert wandb.run._backend.files["*.rad"] == 2


def test_save_absolute_path(wandb_init_run, capsys):
    root = tempfile.gettempdir()
    test_path = os.path.join(root, "test.txt")
    with open(test_path, "w") as f:
        f.write("something")
    wandb.save(test_path)
    _, err = capsys.readouterr()
    assert "Saving files without folders" in err
    assert os.path.exists(os.path.join(wandb_init_run.dir, "test.txt"))
    assert wandb.run._backend.files["test.txt"] == 2


def test_save_relative_path(wandb_init_run):
    root = tempfile.gettempdir()
    test_path = os.path.join(root, "tmp", "test.txt")
    print("DAMN", os.path.dirname(test_path))
    wandb.util.mkdir_exists_ok(os.path.dirname(test_path))
    with open(test_path, "w") as f:
        f.write("something")
    wandb.save(test_path, base_path=root, policy="now")
    assert os.path.exists(os.path.join(wandb_init_run.dir, test_path))
    assert wandb.run._backend.files[os.path.relpath(test_path, root)] == 0


def test_save_invalid_path(wandb_init_run):
    root = tempfile.gettempdir()
    test_path = os.path.join(root, "tmp", "test.txt")
    wandb.util.mkdir_exists_ok(os.path.dirname(test_path))
    with open(test_path, "w") as f:
        f.write("something")
    with pytest.raises(ValueError):
        wandb.save(os.path.join(root, "..", "..", "*.txt"), base_path=root)


def test_restore_no_path(mock_server):
    with pytest.raises(ValueError):
        wandb.restore("weights.h5")


def test_restore_no_init(runner, mock_server):
    with runner.isolated_filesystem():
        mock_server.set_context("files", {"weights.h5": 10000})
        res = wandb.restore("weights.h5", run_path="foo/bar/baz")
        assert os.path.getsize(res.name) == 10000


def test_restore(runner, mock_server, wandb_init_run):
    with runner.isolated_filesystem():
        mock_server.set_context("files", {"weights.h5": 10000})
        res = wandb.restore("weights.h5")
        assert os.path.getsize(res.name) == 10000


def test_restore_name_not_found(runner, mock_server, wandb_init_run):
    with runner.isolated_filesystem():
        with pytest.raises(ValueError):
            wandb.restore("nofile.h5")


@pytest.mark.wandb_args(env={"WANDB_RUN_ID": "123456"})
def test_run_id(wandb_init_run):
    assert wandb.run.id == "123456"


@pytest.mark.wandb_args(env={"WANDB_NAME": "coolio"})
def test_run_name(wandb_init_run):
    assert wandb.run.name == "coolio"


def test_run_setname(wandb_init_run):
    wandb.run.name = "name1"
    assert wandb.run.name == "name1"


@pytest.mark.wandb_args(env={"WANDB_NOTES": "these are my notes"})
def test_run_notes(wandb_init_run):
    assert wandb.run.notes == "these are my notes"


def test_run_setnotes(wandb_init_run):
    wandb.run.notes = "notes1"
    assert wandb.run.notes == "notes1"


@pytest.mark.wandb_args(env={"WANDB_TAGS": "tag1,tag2"})
def test_run_tags(wandb_init_run):
    assert wandb.run.tags == ("tag1", "tag2")


def test_run_settags(wandb_init_run):
    wandb.run.tags = ["mytag1", "mytag2"]
    assert wandb.run.tags == ("mytag1", "mytag2")


def test_run_mode(wandb_init_run):
    assert wandb.run.mode == "dryrun"


def test_run_offline(wandb_init_run):
    assert wandb.run.offline is True


@pytest.mark.wandb_args(env={"WANDB_ENTITY": "ent1"})
def test_run_entity(wandb_init_run):
    assert wandb.run.entity == "ent1"


@pytest.mark.wandb_args(env={"WANDB_PROJECT": "proj1"})
def test_run_project(wandb_init_run):
    assert wandb.run.project == "proj1"


@pytest.mark.wandb_args(env={"WANDB_PROJECT": "proj1"})
def test_run_project(wandb_init_run):
    assert wandb.run.project_name() == "proj1"


@pytest.mark.wandb_args(env={"WANDB_RUN_GROUP": "group1"})
def test_run_group(wandb_init_run):
    assert wandb.run.group == "group1"


@pytest.mark.wandb_args(env={"WANDB_JOB_TYPE": "job1"})
def test_run_jobtype(wandb_init_run):
    assert wandb.run.job_type == "job1"


def test_run_resumed(wandb_init_run):
    assert wandb.run.resumed is False


def test_run_sweepid(wandb_init_run):
    assert wandb.run.sweep_id is None


def test_run_configstatic(wandb_init_run):
    wandb.run.config.update(dict(this=2, that=3))
    assert dict(wandb.run.config_static) == dict(this=2, that=3)


@pytest.mark.wandb_args(
    env={"WANDB_ENTITY": "ent1", "WANDB_PROJECT": "proj1", "WANDB_RUN_ID": "run1"}
)
def test_run_path(wandb_init_run):
    assert wandb.run.path == "ent1/proj1/run1"


def test_run_projecturl(wandb_init_run):
    url = wandb.run.get_project_url()
    # URL is not available offline
    assert url is None


def test_run_sweepurl(wandb_init_run):
    url = wandb.run.get_sweep_url()
    # URL is not available offline
    assert url is None


def test_run_url(wandb_init_run):
    url = wandb.run.get_url()
    # URL is not available offline
    assert url is None
    url = wandb.run.url
    assert url is None


# NOTE: not allowed in 0.10.x:
# run.api
# run.entity="junk"
# run.upload_debug()
# run.host
# run.auto_project_name()
# run.set_environment()
# run.close_files()
# run.has_history()
# run.has_summary()
# run.has_events()
# run.events

# NOTE: deprecated and removed:
# run.description
# run.description_path()

# TODO: test these or make sure they are tested somewhere
# run.save()  # odd
# run.use_artifact()
# run.log_artifact()
