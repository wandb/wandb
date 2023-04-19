import json

import pytest
import yaml
from wandb.sdk.launch.sweeps import utils


def test_parse_sweep_id():
    parts = {"name": "test/test/test"}
    utils.parse_sweep_id(parts)
    assert parts == {"name": "test", "entity": "test", "project": "test"}

    parts = {"name": 1}
    assert utils.parse_sweep_id(parts) == "Expected string sweep_id"

    parts = {"name": "test/test"}
    utils.parse_sweep_id(parts)
    assert parts == {"name": "test", "entity": None, "project": "test"}

    parts = {"name": "test/test/test/test"}
    out = utils.parse_sweep_id(parts)
    assert (
        out
        == "Expected sweep_id in form of sweep, project/sweep, or entity/project/sweep"
    )


def test_load_sweep_config():
    assert not utils.load_sweep_config("s.yaml")

    json.dump({}, open("s.yaml", "w"))
    assert not utils.load_sweep_config("s.yaml")

    json.dump({"metric": "banana"}, open("s.yaml", "w"))
    assert utils.load_sweep_config("s.yaml")

    with open("s1.yaml", "w") as f:
        f.write('{"metric": "banana"')

    with pytest.raises(yaml.parser.ParserError):
        utils.load_launch_sweep_config("s1.yaml")


def test_load_launch_sweep_config():
    assert utils.load_launch_sweep_config(None) == {}

    json.dump({"metric": "banana"}, open("s.yaml", "w"))
    out = utils.load_launch_sweep_config("s.yaml")
    assert out == {"metric": "banana"}

    with open("s1.yaml", "w") as f:
        f.write('{"metric": "banana"')

    with pytest.raises(yaml.parser.ParserError):
        utils.load_launch_sweep_config("s1.yaml")


def test_sweep_construct_scheduler_entrypoint():
    assert utils.construct_scheduler_entrypoint({}, "queue", "project", 1) == []

    assert utils.construct_scheduler_entrypoint(
        {"job": "job:12315"}, "queue", "project", 1
    ) == [
        "wandb",
        "scheduler",
        "WANDB_SWEEP_ID",
        "--queue",
        "'queue'",
        "--project",
        "project",
        "--num_workers",
        "1",
        "--job",
        "job:12315",
    ]

    assert utils.construct_scheduler_entrypoint(
        {"job": "job"}, "queue", "project", "1"
    ) == [
        "wandb",
        "scheduler",
        "WANDB_SWEEP_ID",
        "--queue",
        "'queue'",
        "--project",
        "project",
        "--num_workers",
        "1",
        "--job",
        "job:latest",
    ]

    assert utils.construct_scheduler_entrypoint(
        {"image_uri": "image_uri"}, "queue", "project", 1
    ) == [
        "wandb",
        "scheduler",
        "WANDB_SWEEP_ID",
        "--queue",
        "'queue'",
        "--project",
        "project",
        "--num_workers",
        "1",
        "--image_uri",
        "image_uri",
    ]

    assert (
        utils.construct_scheduler_entrypoint(
            {"job": "job", "image_uri": "image_uri"}, "queue", "project", 1
        )
        == []
    )

    assert (
        utils.construct_scheduler_entrypoint(
            {"job": "job", "image_uri": "image_uri"}, "queue", "project", "1cpu"
        )
        == []
    )

    assert (
        utils.construct_scheduler_entrypoint(
            {"job": "job", "image_uri": "image_uri"}, "queue", "project", "1.5"
        )
        == []
    )
