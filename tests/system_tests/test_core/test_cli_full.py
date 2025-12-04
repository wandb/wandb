import netrc
import os
from unittest import mock

import pytest
import wandb
import wandb.errors.term
from wandb.cli import cli
from wandb.sdk import wandb_setup


@pytest.fixture
def empty_netrc(monkeypatch):
    class FakeNet:
        @property
        def hosts(self):
            return {"api.wandb.ai": None}

    monkeypatch.setattr(netrc, "netrc", lambda *args: FakeNet())


@pytest.mark.xfail(reason="This test is flakey on CI")
def test_init_reinit(runner, empty_netrc, user):
    with runner.isolated_filesystem(), mock.patch(
        "wandb.sdk.lib.apikey.len", return_value=40
    ):
        result = runner.invoke(cli.login, [user])
        result = runner.invoke(cli.init, input="y\n\n\n")
        assert result.exit_code == 0
        with open("netrc") as f:
            generated_netrc = f.read()
        with open("wandb/settings") as f:
            generated_wandb = f.read()
        assert user in generated_netrc
        assert user in generated_wandb


@pytest.mark.xfail(reason="This test is flakey on CI")
def test_init_add_login(runner, empty_netrc, user):
    with runner.isolated_filesystem(), mock.patch(
        "wandb.sdk.lib.apikey.len", return_value=40
    ):
        with open("netrc", "w") as f:
            f.write("previous config")
        result = runner.invoke(cli.login, [user])
        result = runner.invoke(cli.init, input=f"y\n{user}\nvanpelt\n")
        assert result.exit_code == 0
        with open("netrc") as f:
            generated_netrc = f.read()
        with open("wandb/settings") as f:
            generated_wandb = f.read()
        assert user in generated_netrc
        assert user in generated_wandb


@pytest.mark.xfail(reason="This test is flakey on CI")
def test_init_existing_login(runner, user):
    with runner.isolated_filesystem():
        with open("netrc", "w") as f:
            f.write(f"machine localhost\n\tlogin {user}\tpassword {user}")
        result = runner.invoke(cli.init, input="y\nvanpelt\nfoo\n")
        assert result.exit_code == 0
        with open("wandb/settings") as f:
            generated_wandb = f.read()
        assert user in generated_wandb
        assert "This directory is configured" in result.output


@pytest.mark.xfail(reason="This test is flakey on CI")
def test_pull(runner, user):
    with runner.isolated_filesystem():
        project_name = "test_pull"
        file_name = "weights.h5"
        with wandb.init(project=project_name) as run:
            with open(file_name, "w") as f:
                f.write("WEIGHTS")
            run.save(file_name)

        # delete the file so that we can pull it and check that it is there
        os.remove(file_name)

        result = runner.invoke(cli.pull, [run.id, "--project", project_name])
        assert result.exit_code == 0
        assert f"Downloading: {project_name}/{run.id}" in result.output
        assert os.path.isfile(file_name)
        assert f"File {file_name}" in result.output


@pytest.mark.parametrize(
    "tb_file_name,history_length",
    [
        ("events.out.tfevents.1585769947.cvp", 17),
        pytest.param(
            "events.out.tfevents.1611911647.big-histos",
            27,
            marks=[
                pytest.mark.flaky,
                pytest.mark.xfail(reason="test seems flaky, re-enable with WB-5015"),
            ],
        ),
    ],
)
@pytest.mark.skip(reason="TODO: re-enable pending tensorboard support of numpy 2.0")
def test_sync_tensorboard(
    runner,
    wandb_backend_spy,
    copy_asset,
    tb_file_name,
    history_length,
):
    with runner.isolated_filesystem():
        project_name = "test_sync_tensorboard"
        run = wandb.init(project=project_name)
        run.finish()

        copy_asset(tb_file_name)

        result = runner.invoke(
            cli.sync, [".", f"--id={run.id}", f"--project={project_name}"]
        )

        assert result.exit_code == 0
        assert "Found 1 tfevent files" in result.output

        with wandb_backend_spy.freeze() as snapshot:
            history = snapshot.history(run_id=run.id)
            assert len(history) == history_length

        # Check the no sync tensorboard flag
        result = runner.invoke(cli.sync, [".", "--no-sync-tensorboard"])
        assert "Skipping directory: {}\n".format(os.path.abspath(".")) in result.output
        assert tb_file_name in os.listdir(".")


def test_sync_wandb_run(runner, wandb_backend_spy, user, copy_asset):
    # note: we have to mock out ArtifactSaver.save
    # because the artifact does not actually exist
    # among assets listed in the .wandb file.
    # this a problem for a real backend that we use now
    # (as we used to use a mock backend)
    # todo: create a new test asset that will contain an artifact
    with runner.isolated_filesystem(), mock.patch(
        "wandb.sdk.artifacts.artifact_saver.ArtifactSaver.save", return_value=None
    ):
        copy_asset("wandb")

        result = runner.invoke(cli.sync, ["--sync-all"])
        assert result.exit_code == 0

        assert f"{user}/code-toad/runs/g9dvvkua ... done." in result.output
        with wandb_backend_spy.freeze() as snapshot:
            assert len(snapshot.system_metrics(run_id="g9dvvkua")) == 1

        # Check we marked the run as synced
        result = runner.invoke(cli.sync, ["--sync-all"])
        assert result.exit_code == 0
        assert "wandb: ERROR Nothing to sync." in result.output


def test_sync_wandb_run_and_tensorboard(runner, wandb_backend_spy, user, copy_asset):
    with runner.isolated_filesystem(), mock.patch(
        "wandb.sdk.artifacts.artifact_saver.ArtifactSaver.save", return_value=None
    ):
        run_dir = os.path.join("wandb", "offline-run-20210216_154407-g9dvvkua")
        copy_asset("wandb")
        tb_file_name = "events.out.tfevents.1585769947.cvp"
        copy_asset(tb_file_name, os.path.join(run_dir, tb_file_name))

        result = runner.invoke(cli.sync, ["--sync-all"])
        assert result.exit_code == 0

        assert f"{user}/code-toad/runs/g9dvvkua ... done." in result.output
        with wandb_backend_spy.freeze() as snapshot:
            assert len(snapshot.system_metrics(run_id="g9dvvkua")) == 1

            uploaded_files = snapshot.uploaded_files(run_id="g9dvvkua")
            assert "code/standalone_tests/code-toad.py" in uploaded_files

        # Check we marked the run as synced
        result = runner.invoke(cli.sync, [run_dir])
        assert result.exit_code == 0
        assert (
            "WARNING Found .wandb file, not streaming tensorboard metrics"
            in result.output
        )


def test_cli_offline(user, runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli.offline)
        assert result.exit_code == 0
        wandb_setup.singleton().settings.update_from_system_settings()

        with wandb.init() as run:
            assert run.settings._offline
            assert run.settings.mode == "offline"
