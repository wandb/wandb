from unittest import mock

import wandb
from wandb.proto.wandb_telemetry_pb2 import Feature

# TODO: implement the telemetry context resolver


def get_features(telemetry) -> set[str]:
    features = telemetry.get("3", [])
    return {
        Feature.DESCRIPTOR.fields_by_number[feature_number].name
        for feature_number in features
    }


def test_telemetry_finish(wandb_backend_spy):
    with wandb.init(config={"lol": True}) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run.id)
        assert "finish" in get_features(telemetry)


def test_telemetry_imports(wandb_backend_spy):
    transformers_mock = mock.MagicMock()
    transformers_mock.__name__ = "transformers"

    catboost_mock = mock.MagicMock()
    catboost_mock.__name__ = "catboost"

    jax_mock = mock.MagicMock()
    jax_mock.__name__ = "jax"

    with mock.patch.dict(
        "sys.modules",
        {
            "jax": jax_mock,
            "catboost": catboost_mock,
        },
    ):
        __import__("jax")

        run = wandb.init()
        __import__("catboost")
        run.finish()
        with mock.patch.dict(
            "sys.modules",
            {
                "transformers": transformers_mock,
            },
        ):
            __import__("transformers")

    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run.id)
        assert 12 in telemetry.get("2", [])  # jax
        assert 7 in telemetry.get("2", [])  # catboost
        assert 11 not in telemetry.get("2", [])  # transformers


def test_telemetry_run_organizing_init(wandb_backend_spy):
    with wandb.init(
        name="test_name",
        tags=["my-tag"],
        config={"abc": 123},
        id="mynewid",
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run.id)
        assert "set_init_name" in get_features(telemetry)
        assert "set_init_id" in get_features(telemetry)
        assert "set_init_tags" in get_features(telemetry)
        assert "set_init_config" in get_features(telemetry)


def test_telemetry_run_organizing_set(wandb_backend_spy):
    with wandb.init() as run:
        run.name = "test-name"
        run.tags = ["tag1"]
        run.config.update = True

    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run.id)
        assert "set_run_name" in get_features(telemetry)
        assert "set_run_tags" in get_features(telemetry)
        assert "set_config_item" in get_features(telemetry)


def test_telemetry_table_logged_to_run(wandb_backend_spy):
    with wandb.init() as run:
        run.log({"my_table": wandb.Table(columns=["a"], data=[[1]])})

    with wandb_backend_spy.freeze() as snapshot:
        features = get_features(snapshot.telemetry(run_id=run.id))
        assert "table" in features
        assert "incremental_table" not in features


def test_telemetry_incremental_table_logged_to_run(wandb_backend_spy):
    with wandb.init() as run:
        t = wandb.Table(columns=["a"], data=[[1]], log_mode="INCREMENTAL")
        run.log({"my_table": t})
        t.add_data(2)
        run.log({"my_table": t})

    with wandb_backend_spy.freeze() as snapshot:
        features = get_features(snapshot.telemetry(run_id=run.id))
        assert "incremental_table" in features
        assert "table" not in features


def test_telemetry_table_in_artifact_does_not_set_feature(wandb_backend_spy):
    """A Table serialized into an artifact (never logged to the run) must not
    set the run-level table telemetry features.

    Table.to_json records telemetry only in the wandb.Run branch, so artifact
    serialization should leave the table features unset.
    """
    with wandb.init() as run:
        artifact = wandb.Artifact("my_dataset", type="dataset")
        artifact.add(wandb.Table(columns=["a"], data=[[1]]), "my_table")
        run.log_artifact(artifact).wait()

    with wandb_backend_spy.freeze() as snapshot:
        features = get_features(snapshot.telemetry(run_id=run.id))
        # Sanity check that telemetry was captured for this run at all.
        assert "finish" in features
        assert "table" not in features
        assert "incremental_table" not in features
