from unittest import mock

import pytest
import wandb


@pytest.mark.nexus_failure(feature="artifacts")
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
            == "Instances of wandb.Artifact and PublicArtifact can only be top level keys in wandb.config"
        )

    with pytest.raises(ValueError) as e_info:
        run.config.dict_nested = {"one_nest": {"two_nest": artifact}}
        assert (
            str(e_info.value)
            == "Instances of wandb.Artifact and PublicArtifact can only be top level keys in wandb.config"
        )

    with pytest.raises(ValueError) as e_info:
        run.config.update({"one_nest": {"two_nest": artifact}})
        assert (
            str(e_info.value)
            == "Instances of wandb.Artifact and PublicArtifact can only be top level keys in wandb.config"
        )
    run.finish()
    ctx = parse_ctx(live_mock_server.get_ctx())
    assert ctx.config_user["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.source_name.split(":")[0],
        "usedAs": "dataset",
    }

    assert ctx.config_user["myarti"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.source_name.split(":")[0],
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
        "sequenceName": run.config.dataset.source_name.split(":")[0],
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
        "sequenceName": run.config.dataset.source_name.split(":")[0],
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
        "sequenceName": run.config.dataset.source_name.split(":")[0],
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
        "sequenceName": run.config.dataset.source_name.split(":")[0],
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
        "sequenceName": run.config.dataset.source_name.split(":")[0],
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
        "sequenceName": run.config.dataset.source_name.split(":")[0],
        "usedAs": "dataset",
    }


@pytest.mark.nexus_failure(feature="artifacts")
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


@pytest.mark.nexus_failure(feature="artifacts")
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


@pytest.mark.nexus_failure(feature="artifacts")
def test_use_artifact(live_mock_server, test_settings):
    run = wandb.init(settings=test_settings)
    artifact = wandb.Artifact("arti", type="dataset")
    run.use_artifact(artifact)
    artifact.wait()
    assert artifact.digest == "e74a08a632c8151960f676ca9cc4c0a5"
    run.finish()


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
        "sequenceName": art.source_name.split(":")[0],
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
        "sequenceName": art.source_name.split(":")[0],
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
        "sequenceName": art.source_name.split(":")[0],
        "usedAs": "dataset",
    }


@pytest.mark.nexus_failure(feature="artifacts")
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


@pytest.mark.nexus_failure(feature="artifacts")
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
@pytest.mark.nexus_failure(feature="artifacts")
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
