from .utils import runner
import os
import sh
import glob
import json
import time
import signal

train_py = open(os.path.join(os.path.dirname(
    __file__), "fixtures/train.py")).read()


def test_dry_run(runner, monkeypatch):
    print("OH NO", dict(os.environ))
    with runner.isolated_filesystem():
        with open("train.py", "w") as f:
            f.write(train_py)
        res = sh.python("train.py")
        run_dir = glob.glob("wandb/dry*")[0]
        assert "loss:" in res
        meta = json.loads(open(run_dir + "/wandb-metadata.json").read())
        assert meta["state"] == "finished"
        assert meta["program"] == "train.py"
        assert meta["exitcode"] == 0
        assert os.path.exists(run_dir + "/output.log")
        assert os.path.exists(run_dir + "/wandb-history.jsonl")
        assert os.path.exists(run_dir + "/wandb-events.jsonl")
        assert os.path.exists(run_dir + "/wandb-summary.json")


def test_dry_run_exc(runner):
    with runner.isolated_filesystem():
        with open("train.py", "w") as f:
            f.write(train_py.replace("#raise", "raise"))
        try:
            res = sh.python("train.py")
        except sh.ErrorReturnCode as e:
            res = e.stdout
        print(res)
        run_dir = glob.glob("wandb/dry*")[0]
        meta = json.loads(open(run_dir + "/wandb-metadata.json").read())
        assert meta["state"] == "failed"
        assert meta["exitcode"] == 1


def test_dry_run_kill(runner):
    with runner.isolated_filesystem():
        with open("train.py", "w") as f:
            f.write(train_py.replace("#os.kill", "os.kill"))
        res = sh.python("train.py", _bg=True)
        try:
            res.wait()
            print(res)
        except sh.ErrorReturnCode:
            pass
        run_dir = glob.glob("wandb/dry*")[0]
        meta = json.loads(open(run_dir + "/wandb-metadata.json").read())
        assert meta["state"] == "killed"
        assert meta["exitcode"] == 255

# TODO: test server communication
