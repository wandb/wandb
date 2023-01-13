from unittest import mock

# TODO: implement the telemetry context resolver


def test_telemetry_finish(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(config={"lol": True})
        run.finish()

    telemetry = relay.context.get_run_telemetry(run.id)
    assert telemetry and 2 in telemetry.get("3", [])


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
        assert telemetry and 13 in telemetry.get("3", [])  # name
        assert telemetry and 14 in telemetry.get("3", [])  # id
        assert telemetry and 15 in telemetry.get("3", [])  # tags
        assert telemetry and 16 in telemetry.get("3", [])  # config


def test_telemetry_run_organizing_set(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.name = "test-name"
        run.tags = ["tag1"]
        run.config.update = True
        run.finish()

        telemetry = relay.context.get_run_telemetry(run.id)
        assert telemetry and 17 in telemetry.get("3", [])  # name
        assert telemetry and 18 in telemetry.get("3", [])  # tags
        assert telemetry and 19 in telemetry.get("3", [])  # config update
