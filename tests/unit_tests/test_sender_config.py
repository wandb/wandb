from wandb.proto import wandb_internal_pb2
from wandb.sdk.internal import sender_config
from wandb.sdk.lib import telemetry


def test_config_record_update():
    config = sender_config.ConfigState({"b": {"x": 9, "c": "old"}})

    config.update_from_proto(
        wandb_internal_pb2.ConfigRecord(
            update=[
                wandb_internal_pb2.ConfigItem(
                    key="a",
                    value_json="123",
                ),
                wandb_internal_pb2.ConfigItem(
                    nested_key=["b", "c"],
                    value_json='"new"',
                ),
            ]
        )
    )

    assert config.non_internal_config() == {
        "a": 123,
        "b": {"x": 9, "c": "new"},
    }


def test_config_record_remove():
    config = sender_config.ConfigState(
        {
            "x": 1,
            "a": {"b": 2, "y": 3},
        }
    )

    config.update_from_proto(
        wandb_internal_pb2.ConfigRecord(
            remove=[
                wandb_internal_pb2.ConfigItem(key="x"),
                wandb_internal_pb2.ConfigItem(nested_key=["a", "y"]),
            ]
        )
    )

    assert config.non_internal_config() == {"a": {"b": 2}}


def test_to_backend_dict():
    config = sender_config.ConfigState(
        {
            "x": 1,
            "y": {"z": 2},
            "_wandb": {"test": 3},
        }
    )

    backend_dict = config.to_backend_dict(
        telemetry_record=telemetry.TelemetryRecord(),
        framework="some-framework",
        start_time_millis=123454321,
        metric_pbdicts=[],
        environment_record=wandb_internal_pb2.EnvironmentRecord(),
    )

    assert backend_dict == {
        "x": {"desc": None, "value": 1},
        "y": {"desc": None, "value": {"z": 2}},
        "_wandb": {
            "desc": None,
            "value": {
                "test": 3,
                "framework": "some-framework",
                "is_jupyter_run": False,
                "is_kaggle_kernel": False,
                "start_time": 123454321,
                "t": {},
            },
        },
    }
