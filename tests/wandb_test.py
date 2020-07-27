import wandb
import pytest
import tempfile
import glob
import os


def test_log_step(wandb_init_run):
    wandb.log({"acc": 1}, step=5, commit=True)
    assert wandb.run._backend.history[0]["_step"] == 5


@pytest.mark.wandb_args({"env": {"WANDB_SILENT": "true"}})
@pytest.mark.skip(reason="We haven't implemented wandb silent yet")
def test_log_silent(wandb_init_run, capsys):
    wandb.log({"acc": 1})
    _, err = capsys.readouterr()
    assert "wandb: " not in err


def test_log_only_strings_as_keys(wandb_init_run):
    with pytest.raises(TypeError):
        wandb.log({1: 1000})
    with pytest.raises(TypeError):
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
@pytest.mark.skip(
    reason="Sagemaker support not currently implemented, see wandb.util.parse_sm_config"
)
def test_sagemaker(wandb_init_run):
    assert wandb.config.fuckin == "A"
    assert wandb.run.id == "sage-maker"
    assert os.getenv("WANDB_TEST_SECRET") == "TRUE"
    assert wandb.run.group == "sage"


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
    assert len(glob.glob("/tmp/wandb/runs/run-*")) > 0


@pytest.mark.wandb_args(env={"WANDB_DIR": "/tmp"})
def test_custom_dir_env(wandb_init_run):
    assert len(glob.glob("/tmp/wandb/runs/run-*")) > 0


def test_login_key(capsys):
    wandb.login(key="A" * 40)
    out, err = capsys.readouterr()
    assert "Appending key" in err
    assert wandb.api.api_key == "A" * 40


def test_login_existing_key():
    os.environ["WANDB_API_KEY"] = "B" * 40
    wandb.ensure_configured()
    wandb.login()
    assert wandb.api.api_key == "B" * 40
    del os.environ["WANDB_API_KEY"]


@pytest.mark.skip(reason="This doesn't work for some reason")
def test_login_anonymous(mock_server, local_netrc):
    os.environ["WANDB_API_KEY"] = "B" * 40
    wandb.login(anonymous="must")
    assert wandb.api.api_key == "ANONYMOOSE" * 4


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
        wandb.save(os.path.join(root, "..", "..", "*.txt"),
                   base_path=root)


def test_restore(runner, mock_server, wandb_init_run):
    with runner.isolated_filesystem():
        mock_server.set_context("files", {"weights.h5": 10000})
        res = wandb.restore("weights.h5")
        assert os.path.getsize(res.name) == 10000


@pytest.mark.wandb_args(env={"WANDB_RUN_ID": "123456"})
def test_run_id(wandb_init_run):
    assert wandb.run.id == "123456"


@pytest.mark.wandb_args(env={"WANDB_NAME": "coolio"})
@pytest.mark.skip(reason="Not yet supported")
def test_run_name(wandb_init_run):
    assert wandb.run.name == "coolio"
