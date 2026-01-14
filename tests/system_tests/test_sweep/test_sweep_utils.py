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


def test_sweep_construct_scheduler_args():
    assert not utils.construct_scheduler_args({}, "queue", "project")

    args = utils.construct_scheduler_args({"job": "job:12315"}, "queue", "project")
    assert args == [
        "--queue",
        "'queue'",
        "--project",
        "'project'",
        "--job",
        "'job:12315'",
    ]

    args = utils.construct_scheduler_args(
        {"job": "job:12315"},
        "queue",
        "project",
        return_job=False,
    )
    assert args == [
        "--queue",
        "'queue'",
        "--project",
        "'project'",
        "--job",
        "'job:12315'",
    ]

    args = utils.construct_scheduler_args(
        {"job": "job:latest"},
        "queue",
        "project",
        author="author",
        return_job=False,
    )
    assert args == [
        "--queue",
        "'queue'",
        "--project",
        "'project'",
        "--author",
        "'author'",
        "--job",
        "'job:latest'",
    ]

    args = utils.construct_scheduler_args(
        {"image_uri": "image_uri"},
        "queue",
        "project",
        return_job=False,
    )
    assert args == [
        "--queue",
        "'queue'",
        "--project",
        "'project'",
        "--image_uri",
        "image_uri",
    ]

    # should fail because job and image_uri are mutually exclusive
    assert not (
        utils.construct_scheduler_args(
            {"job": "job:111", "image_uri": "image_uri"},
            "queue",
            "project",
            return_job=False,
        )
    )
