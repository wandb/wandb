import json
from wandb.sdk.launch.sweeps import utils


def test_parse_sweep_id():
    parts = {"name": "test/test/test"}
    utils.parse_sweep_id(parts)
    assert parts == {"name": "test", "entity": "test", "project": "test"}

    parts = {"name": 1}
    assert utils.parse_sweep_id(parts) == "Expected string sweep_id"

    parts = {"name": "test/test"}
    out = utils.parse_sweep_id(parts)
    assert out == {"name": "test", "entity": None, "project": "test"}

    parts = {"name": "test/test/test/test"}
    out = utils.parse_sweep_id(parts)
    assert "Expected sweep_id in form of sweep, project/sweep, or entity/project/sweep"


def test_load_sweep_config():
    assert not utils.load_sweep_config("s.yaml")

    json.dump({}, open("s.yaml", "w"))
    assert not utils.load_sweep_config("s.yaml")

    json.dump({"metric": "banana"}, open("s.yaml", "w"))
    assert utils.load_sweep_config("s.yaml")


def test_load_launch_sweep_config():
    assert utils.load_launch_sweep_config(None) == {}

    out = json.dump({"metric": "banana"}, open("s.yaml", "w"))
    assert out == {"metric": "banana"}
