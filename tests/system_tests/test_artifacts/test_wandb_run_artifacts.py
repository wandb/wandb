from __future__ import annotations

import os
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

import wandb
from pytest import FixtureRequest, fixture, mark, raises
from pytest_mock import MockerFixture
from wandb import Artifact, env
from wandb.errors import CommError
from wandb.util import make_artifact_name_safe

if TYPE_CHECKING:
    from wandb import Api

    from tests.fixtures.wandb_backend_spy import WandbBackendSpy


@fixture
def sample_data(user: str) -> Artifact:
    # NOTE: Requesting the `user` fixture is important as it sets auth
    # environment variables for the duration of the test.
    _ = user

    artifact = Artifact("boom-data", type="dataset")
    artifact.save()
    artifact.wait()
    return artifact


@mark.usefixtures("sample_data")
def test_artifacts_in_config(test_settings, api: Api):
    with wandb.init(settings=test_settings()) as run:
        artifact = run.use_artifact("boom-data:v0")
        logged_artifact = Artifact("my-arti", type="dataset")

        run.log_artifact(logged_artifact)
        logged_artifact.wait()

        run.config.dataset = artifact
        run.config.logged_artifact = logged_artifact
        run.config.update({"myarti": artifact})

        expected_msg = (
            "Instances of wandb.Artifact can only be top level keys in a run's config"
        )
        with raises(ValueError, match=expected_msg):
            run.config.nested_dataset = {"nested": artifact}

        with raises(ValueError, match=expected_msg):
            run.config.dict_nested = {"one_nest": {"two_nest": artifact}}

        with raises(ValueError, match=expected_msg):
            run.config.update({"one_nest": {"two_nest": artifact}})

    artifact_id = artifact.id
    artifact_sequence_name = artifact.source_name.split(":")[0]

    logged_artifact_id = logged_artifact.id
    logged_artifact_sequence_name = logged_artifact.source_name.split(":")[0]

    api_run = api.run(f"uncategorized/{run.id}")

    assert api_run.config == {
        "dataset": {
            "_type": "artifactVersion",
            "_version": "v0",
            "id": artifact_id,
            "version": "v0",
            "sequenceName": artifact_sequence_name,
            "usedAs": None,
        },
        "myarti": {
            "_type": "artifactVersion",
            "_version": "v0",
            "id": artifact_id,
            "version": "v0",
            "sequenceName": artifact_sequence_name,
            "usedAs": None,
        },
        "logged_artifact": {
            "_type": "artifactVersion",
            "_version": "v0",
            "id": logged_artifact_id,
            "version": "v0",
            "sequenceName": logged_artifact_sequence_name,
            "usedAs": None,
        },
    }


@mark.usefixtures("sample_data")
def test_artifact_string_run_config_init(user: str, test_settings, api: Api):
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


@mark.usefixtures("sample_data")
def test_artifact_string_run_config_set_item(user: str, test_settings, api: Api):
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
    user: str, sample_data: Artifact, test_settings, api: Api
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
    sample_data: Artifact,
    test_settings,
    api: Api,
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
    sample_data: Artifact,
    test_settings,
    api: Api,
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


@mark.usefixtures("sample_data")
def test_artifact_string_run_config_update(user: str, test_settings, api: Api):
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
    artifact = Artifact("test_reference_download", "dataset")
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
    artifact = Artifact("test_reference_download", "dataset")
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
        artifact = Artifact("arti", type="dataset")
        run.use_artifact(artifact)
        artifact.wait()
        assert artifact.digest == "64e7c61456b10382e2f3b571ac24b659"


@mark.usefixtures("sample_data")
def test_public_artifact_run_config_init(test_settings, api: Api):
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


@mark.usefixtures("sample_data")
def test_public_artifact_run_config_set_item(test_settings, api: Api):
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


@mark.usefixtures("sample_data")
def test_public_artifact_run_config_update(test_settings, api: Api):
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
    artifact = Artifact("test_reference_download", "dataset")
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


@fixture(params=[True, False])
def env_save_code(request: FixtureRequest, mocker: MockerFixture, user: str) -> bool:
    """Parametrizes the test with a patched value for the SAVE_CODE env var."""
    # NOTE: Requesting the `user` fixture is important as it sets auth
    # environment variables for the duration of the test.
    _ = user

    mocker.patch.dict(os.environ, {env.SAVE_CODE: str(request.param).lower()})
    return request.param


def test_log_code_env(
    env_save_code: bool,
    api: Api,
    wandb_backend_spy: WandbBackendSpy,
):
    # test for WB-7468

    # simulate user turning on code saving in UI
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="Viewer"),
        gql.once(
            content={"data": {"viewer": {"flags": '{"code_saving_enabled": true}'}}},
            status=200,
        ),
    )

    Path("test.py").write_text('print("test")')

    settings = wandb.Settings(save_code=None, code_dir=".")
    with wandb.init(settings=settings) as run:
        assert run._settings.save_code is env_save_code

    artifact_name = make_artifact_name_safe(
        f"source-{run.project}-{run._settings.program_relpath}"
    )
    expectation = nullcontext() if env_save_code else raises(CommError)
    with expectation:
        api.artifact(f"{artifact_name}:v0")
