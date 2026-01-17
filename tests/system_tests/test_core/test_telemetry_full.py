from unittest import mock

import wandb
from wandb.proto.v3.wandb_telemetry_pb2 import Feature

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
