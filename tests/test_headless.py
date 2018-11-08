from .utils import runner
import os
import sh
import glob
import json
import time
import signal

train_py = open(os.path.join(os.path.dirname(
    __file__), "fixtures/train.py")).read()


def test_dry_run(runner):
    with runner.isolated_filesystem():
        with open("train.py", "w") as f:
            f.write(train_py)
        os.environ["WANDB_MODE"] = "dryrun"
        os.environ["WANDB_TEST"] = "true"
        try:
            res = sh.python("train.py")
            print("RUN", res)
            run_dir = glob.glob("wandb/dry*")[0]
            meta = json.loads(open(run_dir + "/wandb-metadata.json").read())
            assert meta["state"] == "finished"
            assert meta["program"] == "train.py"
            assert meta["exitcode"] == 0
            assert os.path.exists(run_dir + "/output.log")
            assert "loss:" in open(run_dir + "/output.log").read()
            assert os.path.exists(run_dir + "/wandb-history.jsonl")
            assert os.path.exists(run_dir + "/wandb-events.jsonl")
            assert os.path.exists(run_dir + "/wandb-summary.json")
        finally:
            del os.environ["WANDB_MODE"]
            del os.environ["WANDB_TEST"]


def test_dry_run_custom_dir(runner):
    with runner.isolated_filesystem():
        os.environ["WANDB_DIR"] = "/tmp"
        os.environ["WANDB_MODE"] = "dryrun"
        os.environ["WANDB_TEST"] = "true"
        try:
            with open("train.py", "w") as f:
                f.write(train_py)
            res = sh.python("train.py")
            print(res)
            run_dir = glob.glob("/tmp/wandb/dry*")[0]
            assert os.path.exists(run_dir + "/output.log")
        finally:  # avoid stepping on other tests, even if this one fails
            del os.environ["WANDB_DIR"]
            del os.environ["WANDB_MODE"]
            del os.environ["WANDB_TEST"]
            # TODO: this isn't working
            sh.rm("-rf", "/tmp/wandb")


def test_dry_run_exc(runner):
    with runner.isolated_filesystem():
        with open("train.py", "w") as f:
            f.write(train_py.replace("#raise", "raise"))
        os.environ["WANDB_MODE"] = "dryrun"
        os.environ["WANDB_TEST"] = "true"
        try:
            try:
                res = sh.python("train.py")
            except sh.ErrorReturnCode as e:
                res = e.stdout
            print(res)
            run_dir = glob.glob("wandb/dry*")[0]
            meta = json.loads(open(run_dir + "/wandb-metadata.json").read())
            assert meta["state"] == "failed"
            assert meta["exitcode"] == 1
        finally:
            del os.environ["WANDB_MODE"]
            del os.environ["WANDB_TEST"]


def test_dry_run_kill(runner):
    with runner.isolated_filesystem():
        with open("train.py", "w") as f:
            f.write(train_py.replace("#os.kill", "os.kill"))
        os.environ["WANDB_MODE"] = "dryrun"
        os.environ["WANDB_TEST"] = "true"
        try:
            res = sh.python("train.py", _bg=True)
            try:
                res.wait()
                print(res)
            except sh.ErrorReturnCode:
                pass
            dirs = glob.glob("wandb/dry*")
            print(dirs)
            run_dir = dirs[0]
            meta = json.loads(open(run_dir + "/wandb-metadata.json").read())
            assert meta["state"] == "killed"
            assert meta["exitcode"] == 255
        finally:
            del os.environ["WANDB_MODE"]
            del os.environ["WANDB_TEST"]

# TODO: test server communication
