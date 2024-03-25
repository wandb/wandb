import json
import os
from unittest import mock

import pytest
import wandb


@pytest.fixture
def sample_data():
    artifact = wandb.Artifact("boom-data", type="dataset")
    artifact.save()
    artifact.wait()
    yield artifact


def test_artifacts_in_config(user, sample_data, test_settings):
    with wandb.init(settings=test_settings()) as run:
        artifact = run.use_artifact("boom-data:v0")
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
            == "Instances of wandb.Artifact can only be top level keys in wandb.config"
        )

        with pytest.raises(ValueError) as e_info:
            run.config.dict_nested = {"one_nest": {"two_nest": artifact}}
        assert (
            str(e_info.value)
            == "Instances of wandb.Artifact can only be top level keys in wandb.config"
        )

        with pytest.raises(ValueError) as e_info:
            run.config.update({"one_nest": {"two_nest": artifact}})
        assert (
            str(e_info.value)
            == "Instances of wandb.Artifact can only be top level keys in wandb.config"
        )

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.source_name.split(":")[0],
        "usedAs": "dataset",
    }

    assert run.config["myarti"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.source_name.split(":")[0],
        "usedAs": "myarti",
    }

    assert run.config["logged_artifact"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": logged_artifact.id,
        "version": "v0",
        "sequenceName": logged_artifact.name.split(":")[0],
        "usedAs": "logged_artifact",
    }


def test_artifact_string_run_config_init(user, sample_data, test_settings):
    config = {"dataset": f"wandb-artifact://{user}/uncategorized/boom-data:v0"}
    with wandb.init(settings=test_settings(), config=config) as run:
        dataset = run.config.dataset

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": "dataset",
    }


def test_artifact_string_run_config_set_item(user, sample_data, test_settings):
    with wandb.init(settings=test_settings()) as run:
        run.config.dataset = f"wandb-artifact://{run.settings.base_url}/{user}/uncategorized/boom-data:v0"
        dataset = run.config.dataset

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": "dataset",
    }


def test_artifact_string_digest_run_config_update(user, sample_data, test_settings):
    with wandb.init(settings=test_settings()) as run:
        run.config.update({"dataset": f"wandb-artifact://_id/{sample_data.id}"})
        dataset = run.config.dataset

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": "dataset",
    }


def test_artifact_string_digest_run_config_init(user, sample_data, test_settings):
    config = {"dataset": f"wandb-artifact://_id/{sample_data.id}"}
    with wandb.init(settings=test_settings(), config=config) as run:
        dataset = run.config.dataset

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": "dataset",
    }


def test_artifact_string_digest_run_config_set_item(user, sample_data, test_settings):
    with wandb.init(settings=test_settings()) as run:
        run.config.dataset = (
            f"wandb-artifact://{run.settings.base_url}/_id/{sample_data.id}"
        )
        dataset = run.config.dataset

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": "dataset",
    }


def test_artifact_string_run_config_update(user, sample_data, test_settings):
    with wandb.init(settings=test_settings()) as run:
        run.config.update(
            {"dataset": f"wandb-artifact://{user}/uncategorized/boom-data:v0"}
        )
        dataset = run.config.dataset

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": "dataset",
    }


def test_wandb_artifact_config_update(user, test_settings):
    open("file1.txt", "w").write("hello")
    artifact = wandb.Artifact("test_reference_download", "dataset")
    artifact.add_file("file1.txt")
    artifact.add_reference(
        "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
    )
    with wandb.init(settings=test_settings()) as run:
        run.config.update({"test_reference_download": artifact})
        assert run.config.test_reference_download == artifact

    run = wandb.Api().run(f"uncategorized/{run.id}")
    config_art = {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.name.split(":")[0],
        "usedAs": "test_reference_download",
    }
    assert run.config["test_reference_download"] == config_art

    with wandb.init(settings=test_settings()) as run:
        run.config.update({"test_reference_download": config_art})
        assert run.config.test_reference_download.id == artifact.id


def test_wandb_artifact_config_set_item(user, test_settings):
    open("file1.txt", "w").write("hello")
    artifact = wandb.Artifact("test_reference_download", "dataset")
    artifact.add_file("file1.txt")
    artifact.add_reference(
        "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
    )
    with wandb.init(settings=test_settings()) as run:
        run.config.test_reference_download = artifact
        assert run.config.test_reference_download == artifact

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["test_reference_download"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.name.split(":")[0],
        "usedAs": "test_reference_download",
    }


def test_use_artifact(user, test_settings):
    with wandb.init(settings=test_settings()) as run:
        artifact = wandb.Artifact("arti", type="dataset")
        run.use_artifact(artifact)
        artifact.wait()
        assert artifact.digest == "64e7c61456b10382e2f3b571ac24b659"


def test_public_artifact_run_config_init(user, sample_data, test_settings):
    art = wandb.Api().artifact("boom-data:v0", type="dataset")
    config = {"dataset": art}
    with wandb.init(settings=test_settings(), config=config) as run:
        assert run.config.dataset == art

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": art.id,
        "version": "v0",
        "sequenceName": art.source_name.split(":")[0],
        "usedAs": "dataset",
    }


def test_public_artifact_run_config_set_item(user, sample_data, test_settings):
    art = wandb.Api().artifact("boom-data:v0", type="dataset")
    with wandb.init(settings=test_settings()) as run:
        run.config.dataset = art
        assert run.config.dataset == art

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": art.id,
        "version": "v0",
        "sequenceName": art.source_name.split(":")[0],
        "usedAs": "dataset",
    }


def test_public_artifact_run_config_update(user, sample_data, test_settings):
    art = wandb.Api().artifact("boom-data:v0", type="dataset")
    config = {"dataset": art}
    with wandb.init(settings=test_settings()) as run:
        run.config.update(config)
        assert run.config.dataset == art

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": art.id,
        "version": "v0",
        "sequenceName": art.source_name.split(":")[0],
        "usedAs": "dataset",
    }


def test_wandb_artifact_init_config(user, test_settings):
    open("file1.txt", "w").write("hello")
    artifact = wandb.Artifact("test_reference_download", "dataset")
    artifact.add_file("file1.txt")
    artifact.add_reference(
        "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
    )
    config = {"test_reference_download": artifact}
    with wandb.init(settings=test_settings(), config=config) as run:
        assert run.config.test_reference_download == artifact

    run = wandb.Api().run(f"uncategorized/{run.id}")
    assert run.config["test_reference_download"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.name.split(":")[0],
        "usedAs": "test_reference_download",
    }


def test_log_code_settings(user, test_settings):
    with open("test.py", "w") as f:
        f.write('print("test")')
    settings = test_settings()
    settings.update(
        save_code=True, code_dir=".", source=wandb.sdk.wandb_settings.Source.INIT
    )
    with wandb.init(settings=settings) as run:
        pass

    artifact_name = wandb.util.make_artifact_name_safe(
        f"source-{run._project}-{run._settings.program_relpath}"
    )
    wandb.Api().artifact(f"{artifact_name}:v0")


@pytest.mark.parametrize("save_code", [True, False])
def test_log_code_env(
    user, test_settings, relay_server, inject_graphql_response, save_code
):
    # test for WB-7468
    with mock.patch.dict("os.environ", WANDB_SAVE_CODE=str(save_code).lower()):
        with open("test.py", "w") as f:
            f.write('print("test")')

        # simulate user turning on code saving in UI
        server_info_response = inject_graphql_response(
            # request
            query_match_fn=lambda query, variables: query.startswith("query Viewer"),
            # response
            body=json.dumps(
                {"data": {"viewer": {"flags": """{"code_saving_enabled": true}"""}}}
            ),
        )
        with relay_server(inject=[server_info_response]):
            settings = test_settings()
            settings.update(save_code=None, source=wandb.sdk.wandb_settings.Source.BASE)
            settings.update(
                code_dir=".", source=wandb.sdk.wandb_settings.Source.SETTINGS
            )
            with wandb.init(settings=settings) as run:
                assert run._settings.save_code is save_code

            artifact_name = wandb.util.make_artifact_name_safe(
                f"source-{run._project}-{run._settings.program_relpath}"
            )
            if save_code:
                wandb.Api().artifact(f"{artifact_name}:v0")
            else:
                with pytest.raises(wandb.errors.CommError):
                    wandb.Api().artifact(f"{artifact_name}:v0")


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
