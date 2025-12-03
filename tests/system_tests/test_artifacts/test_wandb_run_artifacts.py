from __future__ import annotations

import os
from contextlib import nullcontext
from pathlib import Path

import wandb
from pytest import FixtureRequest, fixture, mark, raises
from pytest_mock import MockerFixture
from wandb import Api
from wandb.errors import CommError
from wandb.util import make_artifact_name_safe


@fixture
def sample_data():
    artifact = wandb.Artifact("boom-data", type="dataset")
    artifact.save()
    artifact.wait()
    yield artifact


def test_artifacts_in_config(user: str, sample_data, test_settings, api: Api):
    with wandb.init(settings=test_settings()) as run:
        artifact = run.use_artifact("boom-data:v0")
        logged_artifact = wandb.Artifact("my-arti", type="dataset")
        run.log_artifact(logged_artifact)
        logged_artifact.wait()
        run.config.dataset = artifact
        run.config.logged_artifact = logged_artifact
        run.config.update({"myarti": artifact})
        with raises(ValueError) as e_info:
            run.config.nested_dataset = {"nested": artifact}
        assert str(e_info.value) == (
            "Instances of wandb.Artifact can only be top level keys in a run's config"
        )

        with raises(ValueError) as e_info:
            run.config.dict_nested = {"one_nest": {"two_nest": artifact}}
        assert str(e_info.value) == (
            "Instances of wandb.Artifact can only be top level keys in a run's config"
        )

        with raises(ValueError) as e_info:
            run.config.update({"one_nest": {"two_nest": artifact}})
        assert str(e_info.value) == (
            "Instances of wandb.Artifact can only be top level keys in a run's config"
        )

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.source_name.split(":")[0],
        "usedAs": None,
    }

    assert run.config["myarti"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.source_name.split(":")[0],
        "usedAs": None,
    }

    assert run.config["logged_artifact"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": logged_artifact.id,
        "version": "v0",
        "sequenceName": logged_artifact.name.split(":")[0],
        "usedAs": None,
    }


def test_artifact_string_run_config_init(
    user: str, sample_data, test_settings, api: Api
):
    config = {"dataset": f"wandb-artifact://{user}/uncategorized/boom-data:v0"}
    with wandb.init(settings=test_settings(), config=config) as run:
        dataset = run.config.dataset

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": None,
    }


def test_artifact_string_run_config_set_item(
    user: str, sample_data, test_settings, api: Api
):
    with wandb.init(settings=test_settings()) as run:
        run.config.dataset = f"wandb-artifact://{run.settings.base_url}/{user}/uncategorized/boom-data:v0"
        dataset = run.config.dataset

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": None,
    }


def test_artifact_string_digest_run_config_update(
    user: str, sample_data, test_settings, api: Api
):
    with wandb.init(settings=test_settings()) as run:
        run.config.update({"dataset": f"wandb-artifact://_id/{sample_data.id}"})
        dataset = run.config.dataset

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": None,
    }


def test_artifact_string_digest_run_config_init(
    user: str, sample_data, test_settings, api: Api
):
    config = {"dataset": f"wandb-artifact://_id/{sample_data.id}"}
    with wandb.init(settings=test_settings(), config=config) as run:
        dataset = run.config.dataset

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": None,
    }


def test_artifact_string_digest_run_config_set_item(
    user: str, sample_data, test_settings, api: Api
):
    with wandb.init(settings=test_settings()) as run:
        run.config.dataset = (
            f"wandb-artifact://{run.settings.base_url}/_id/{sample_data.id}"
        )
        dataset = run.config.dataset

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": None,
    }


def test_artifact_string_run_config_update(
    user: str, sample_data, test_settings, api: Api
):
    with wandb.init(settings=test_settings()) as run:
        run.config.update(
            {"dataset": f"wandb-artifact://{user}/uncategorized/boom-data:v0"}
        )
        dataset = run.config.dataset

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": dataset.id,
        "version": "v0",
        "sequenceName": dataset.source_name.split(":")[0],
        "usedAs": None,
    }


def test_wandb_artifact_config_update(user: str, test_settings, api: Api):
    Path("file1.txt").write_text("hello")
    artifact = wandb.Artifact("test_reference_download", "dataset")
    artifact.add_file("file1.txt")
    artifact.add_reference(
        "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
    )
    with wandb.init(settings=test_settings()) as run:
        run.config.update({"test_reference_download": artifact})
        assert run.config.test_reference_download == artifact

    run = api.run(f"uncategorized/{run.id}")
    config_art = {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.name.split(":")[0],
        "usedAs": None,
    }
    assert run.config["test_reference_download"] == config_art

    with wandb.init(settings=test_settings()) as run:
        run.config.update({"test_reference_download": config_art})
        assert run.config.test_reference_download.id == artifact.id


def test_wandb_artifact_config_set_item(user: str, test_settings, api: Api):
    Path("file1.txt").write_text("hello")
    artifact = wandb.Artifact("test_reference_download", "dataset")
    artifact.add_file("file1.txt")
    artifact.add_reference(
        "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
    )
    with wandb.init(settings=test_settings()) as run:
        run.config.test_reference_download = artifact
        assert run.config.test_reference_download == artifact

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["test_reference_download"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.name.split(":")[0],
        "usedAs": None,
    }


def test_use_artifact(user, test_settings):
    with wandb.init(settings=test_settings()) as run:
        artifact = wandb.Artifact("arti", type="dataset")
        run.use_artifact(artifact)
        artifact.wait()
        assert artifact.digest == "64e7c61456b10382e2f3b571ac24b659"


def test_public_artifact_run_config_init(
    user: str, sample_data, test_settings, api: Api
):
    art = api.artifact("boom-data:v0", type="dataset")
    config = {"dataset": art}
    with wandb.init(settings=test_settings(), config=config) as run:
        assert run.config.dataset == art

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": art.id,
        "version": "v0",
        "sequenceName": art.source_name.split(":")[0],
        "usedAs": None,
    }


def test_public_artifact_run_config_set_item(
    user: str, sample_data, test_settings, api: Api
):
    art = api.artifact("boom-data:v0", type="dataset")
    with wandb.init(settings=test_settings()) as run:
        run.config.dataset = art
        assert run.config.dataset == art

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": art.id,
        "version": "v0",
        "sequenceName": art.source_name.split(":")[0],
        "usedAs": None,
    }


def test_public_artifact_run_config_update(
    user: str, sample_data, test_settings, api: Api
):
    art = api.artifact("boom-data:v0", type="dataset")
    config = {"dataset": art}
    with wandb.init(settings=test_settings()) as run:
        run.config.update(config)
        assert run.config.dataset == art

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["dataset"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": art.id,
        "version": "v0",
        "sequenceName": art.source_name.split(":")[0],
        "usedAs": None,
    }


def test_wandb_artifact_init_config(user: str, test_settings, api: Api):
    Path("file1.txt").write_text("hello")
    artifact = wandb.Artifact("test_reference_download", "dataset")
    artifact.add_file("file1.txt")
    artifact.add_reference(
        "https://wandb-artifacts-refs-public-test.s3-us-west-2.amazonaws.com/StarWars3.wav"
    )
    config = {"test_reference_download": artifact}
    with wandb.init(settings=test_settings(), config=config) as run:
        assert run.config.test_reference_download == artifact

    run = api.run(f"uncategorized/{run.id}")
    assert run.config["test_reference_download"] == {
        "_type": "artifactVersion",
        "_version": "v0",
        "id": artifact.id,
        "version": "v0",
        "sequenceName": artifact.name.split(":")[0],
        "usedAs": None,
    }


def test_log_code_settings(user: str, api: Api):
    Path("test.py").write_text('print("test")')

    settings = wandb.Settings(save_code=True, code_dir=".")
    with wandb.init(settings=settings) as run:
        pass

    artifact_name = make_artifact_name_safe(
        f"source-{run.project}-{run._settings.program_relpath}"
    )
    api.artifact(f"{artifact_name}:v0")


@mark.parametrize("save_code", [True, False])
def test_log_code_env(
    request: FixtureRequest, mocker: MockerFixture, wandb_backend_spy, save_code
):
    # test for WB-7468
    mocker.patch.dict(os.environ, WANDB_SAVE_CODE=str(save_code).lower())

    Path("test.py").write_text('print("test")')

    # simulate user turning on code saving in UI
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="Viewer"),
        gql.once(
            content={
                "data": {"viewer": {"flags": """{"code_saving_enabled": true}"""}}
            },
            status=200,
        ),
    )

    # The Api fixture must be requested AFTER the response is stubbed/mocked
    api = request.getfixturevalue("api")

    settings = wandb.Settings(save_code=None, code_dir=".")
    with wandb.init(settings=settings) as run:
        assert run._settings.save_code is save_code

    artifact_name = make_artifact_name_safe(
        f"source-{run.project}-{run._settings.program_relpath}"
    )
    expectation = nullcontext() if save_code else raises(CommError)
    with expectation:
        api.artifact(f"{artifact_name}:v0")
