from typing import AbstractSet
from unittest import mock

from wandb.proto.v3.wandb_telemetry_pb2 import Feature

# TODO: implement the telemetry context resolver


def get_features(telemetry) -> AbstractSet[str]:
    features = telemetry.get("3", [])
    return {
        Feature.DESCRIPTOR.fields_by_number[feature_number].name
        for feature_number in features
    }


def test_telemetry_finish(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(config={"lol": True})
        run.finish()

    telemetry = relay.context.get_run_telemetry(run.id)
    assert telemetry
    assert "finish" in get_features(telemetry)


def test_telemetry_imports(relay_server, wandb_init):
    with relay_server() as relay:
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

            run = wandb_init()
            __import__("catboost")
            run.finish()
            with mock.patch.dict(
                "sys.modules",
                {
                    "transformers": transformers_mock,
                },
            ):
                __import__("transformers")

    telemetry = relay.context.get_run_telemetry(run.id)
    assert telemetry
    assert 12 in telemetry.get("2", [])  # jax
    assert 7 in telemetry.get("2", [])  # catboost
    assert 11 not in telemetry.get("2", [])  # transformers


def test_telemetry_run_organizing_init(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(
            name="test_name", tags=["my-tag"], config={"abc": 123}, id="mynewid"
        )
        run.finish()

        telemetry = relay.context.get_run_telemetry(run.id)
        assert "set_init_name" in get_features(telemetry)
        assert "set_init_id" in get_features(telemetry)
        assert "set_init_tags" in get_features(telemetry)
        assert "set_init_config" in get_features(telemetry)


def test_telemetry_run_organizing_set(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.name = "test-name"
        run.tags = ["tag1"]
        run.config.update = True
        run.finish()

        telemetry = relay.context.get_run_telemetry(run.id)
        assert "set_run_name" in get_features(telemetry)
        assert "set_run_tags" in get_features(telemetry)
        assert "set_config_item" in get_features(telemetry)


def test_telemetry_logs_settings_flags(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(settings={"_async_upload_concurrency_limit": 123})
        run.finish()

    telemetry = relay.context.get_run_telemetry(run.id)
    assert "async_uploads" in get_features(telemetry)
