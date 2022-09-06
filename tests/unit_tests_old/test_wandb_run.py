"""
config tests.
"""

import os
from unittest import mock

import git
import pytest
import wandb
from wandb import env


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
    assert artifact_name == wandb.util.make_artifact_name_safe(
        f"source-{run._project}-{run._settings.program_relpath}"
    )


@pytest.mark.parametrize("save_code", [True, False])
def test_log_code_env(live_mock_server, test_settings, save_code):
    # test for WB-7468
    with mock.patch.dict("os.environ", WANDB_SAVE_CODE=str(save_code).lower()):
        with open("test.py", "w") as f:
            f.write('print("test")')

        # simulate user turning on code saving in UI
        live_mock_server.set_ctx({"code_saving_enabled": True})
        test_settings.update(
            save_code=None,
            source=wandb.sdk.wandb_settings.Source.BASE,
        )
        test_settings.update(
            code_dir=".", source=wandb.sdk.wandb_settings.Source.SETTINGS
        )
        run = wandb.init(settings=test_settings)
        assert run._settings.save_code is save_code
        run.finish()

        ctx = live_mock_server.get_ctx()
        artifact_names = list(ctx["artifacts"].keys())
        if save_code:
            assert artifact_names[0] == wandb.util.make_artifact_name_safe(
                f"source-{run._project}-{run._settings.program_relpath}"
            )
        else:
            assert len(artifact_names) == 0


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

    msg = "version of W&B Server to get the latest features"

    if empty_query:
        assert msg in captured
    elif local_none:
        assert msg not in captured
    else:
        assert msg in captured if outdated else msg not in captured


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


def test_artifact_string_run_config_init(live_mock_server, test_settings, parse_ctx):
    config = {"dataset": "wandb-artifact://entity/project/boom-data"}
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
    run.config.dataset = (
        f"wandb-artifact://{test_settings.base_url}/entity/project/boom-data"
    )
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


def test_artifact_string_digest_run_config_update(
    runner, live_mock_server, test_settings, parse_ctx
):
    run = wandb.init(settings=test_settings)
    run.config.update({"dataset": "wandb-artifact://_id/abc123"})
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


def test_artifact_string_digest_run_config_init(
    live_mock_server, test_settings, parse_ctx
):
    config = {"dataset": "wandb-artifact://_id/abc123"}
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


def test_artifact_string_digest_run_config_set_item(
    runner, live_mock_server, test_settings, parse_ctx
):
    run = wandb.init(settings=test_settings)
    run.config.dataset = f"wandb-artifact://{test_settings.base_url}/_id/abc123"
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
    run.config.update({"dataset": "wandb-artifact://entity/project/boom-data"})
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
        with wandb.init(settings=test_settings) as run:
            run.config.update({"test_reference_download": artifact})

            assert run.config.test_reference_download == artifact

        ctx = parse_ctx(live_mock_server.get_ctx())
        config_art = {
            "_type": "artifactVersion",
            "_version": "v0",
            "id": artifact.id,
            "version": "v0",
            "sequenceName": artifact.name.split(":")[0],
            "usedAs": "test_reference_download",
        }
        assert ctx.config_user["test_reference_download"] == config_art

        with wandb.init(settings=test_settings) as run:
            run.config.update({"test_reference_download": config_art})
            assert run.config.test_reference_download.id == artifact.id


def test_repo_job_creation(live_mock_server, test_settings, git_repo_fn):
    _ = git_repo_fn(commit_msg="initial commit")
    test_settings.update(
        {"enable_job_creation": True, "program_relpath": "./blah/test_program.py"}
    )
    run = wandb.init(settings=test_settings)
    run.finish()
    ctx = live_mock_server.get_ctx()
    artifact_name = list(ctx["artifacts"].keys())[0]
    assert artifact_name == wandb.util.make_artifact_name_safe(
        f"job-{run._settings.git_remote_url}_{run._settings.program_relpath}"
    )


def test_artifact_job_creation(live_mock_server, test_settings, runner):
    with runner.isolated_filesystem():
        with open("test.py", "w") as f:
            f.write('print("test")')
        test_settings.update(
            {
                "enable_job_creation": True,
                "disable_git": True,
                "program_relpath": "./blah/test_program.py",
            }
        )
        run = wandb.init(settings=test_settings)
        run.log_code()
        run.finish()
        ctx = live_mock_server.get_ctx()
        code_artifact_name = list(ctx["artifacts"].keys())[0]
        job_artifact_name = list(ctx["artifacts"].keys())[1]
        assert job_artifact_name == f"job-{code_artifact_name}"


def test_container_job_creation(live_mock_server, test_settings):
    test_settings.update({"enable_job_creation": True, "disable_git": True})
    with mock.patch.dict("os.environ", WANDB_DOCKER="dummy-container:v0"):
        run = wandb.init(settings=test_settings)
        run.finish()
        ctx = live_mock_server.get_ctx()
        artifact_name = list(ctx["artifacts"].keys())[0]
        assert artifact_name == "job-dummy-container_v0"


def test_manual_git_run_metadata_from_settings(live_mock_server, test_settings):
    remote_url = "git@github.com:me/my-repo.git"
    commit = "29c15e893e36efad84001f4484b4813fbacd55a0"
    test_settings.update(
        {
            "git_remote_url": remote_url,
            "git_commit": commit,
        }
    )
    run = wandb.init(settings=test_settings)
    run.finish()
    ctx = live_mock_server.get_ctx()
    assert ctx["git"]["remote"] == remote_url
    assert ctx["git"]["commit"] == commit


def test_manual_git_run_metadata_from_environ(live_mock_server, test_settings):
    remote_url = "git@github.com:me/my-repo.git"
    commit = "29c15e893e36efad84001f4484b4813fbacd55a0"
    with mock.patch.dict(
        os.environ,
        {
            env.GIT_REMOTE_URL: remote_url,
            env.GIT_COMMIT: commit,
        },
    ):
        run = wandb.init(settings=test_settings)
        run.finish()

    ctx = live_mock_server.get_ctx()
    assert ctx["git"]["remote"] == remote_url
    assert ctx["git"]["commit"] == commit


def test_git_root(runner, live_mock_server, test_settings):
    path = "./foo"
    remote_url = "https://foo:@github.com/FooTest/Foo.git"
    with runner.isolated_filesystem():
        with git.Repo.init(path) as repo:
            repo.create_remote("origin", remote_url)
            repo.index.commit("initial commit")
        with mock.patch.dict(os.environ, {env.GIT_ROOT: path}):
            run = wandb.init(settings=test_settings)
            run.finish()
        ctx = live_mock_server.get_ctx()
        assert ctx["git"]["remote"] == repo.remote().url
        assert ctx["git"]["commit"] == repo.head.commit.hexsha
