from .utils import runner
import os
import sh
import sys
import glob
import json
import time
import signal
import tempfile
import pytest

train_py = open(os.path.join(os.path.dirname(
    __file__), "fixtures/train.py")).read()


def test_dry_run(runner):
    with runner.isolated_filesystem():
        with open("train.py", "w") as f:
            f.write(train_py)
        environ = {
            "WANDB_MODE": "dryrun",
            "WANDB_TEST": "true",
        }
        res = sh.python("train.py", _env=environ)
        run_dir = glob.glob(os.path.join("wandb", "dry*"))[0]
        meta = json.loads(
            open(os.path.join(run_dir, "wandb-metadata.json")).read())
        assert meta["state"] == "finished"
        assert meta["program"] == "train.py"
        assert meta["exitcode"] == 0
        assert os.path.exists(os.path.join(run_dir, "output.log"))
        # TODO: FLAKY SPEC Sometimes output.log is empty...
        assert "loss:" in open(os.path.join(run_dir, "output.log")).read()
        assert os.path.exists(os.path.join(
            run_dir, "wandb-history.jsonl"))
        assert os.path.exists(os.path.join(run_dir, "wandb-events.jsonl"))
        assert os.path.exists(os.path.join(run_dir, "wandb-summary.json"))


def test_dry_run_custom_dir(runner):
    with runner.isolated_filesystem():
        environ = {
            "WANDB_DIR": tempfile.mkdtemp(),
            "WANDB_MODE": "dryrun",
            "WANDB_TEST": "true",
        }
        try:
            with open("train.py", "w") as f:
                f.write(train_py)
            res = sh.python("train.py", _env=environ, _err=1)
            print(res)
            run_dir = glob.glob(os.path.join(
                environ["WANDB_DIR"], "wandb", "dry*"))[0]
            assert os.path.exists(run_dir + "/output.log")
        finally:  # avoid stepping on other tests, even if this one fails
            sh.rm("-rf", environ["WANDB_DIR"])


def test_dry_run_exc(runner):
    with runner.isolated_filesystem():
        with open("train.py", "w") as f:
            f.write(train_py.replace("#raise", "raise"))
        environ = {
            "WANDB_MODE": "dryrun",
            "WANDB_TEST": "true",
        }
        try:
            res = sh.python("train.py", _env=environ)
        except sh.ErrorReturnCode as e:
            res = e.stderr
        print(res)
        run_dir = glob.glob(os.path.join("wandb", "dry*"))[0]
        meta = json.loads(
            open(os.path.join(run_dir, "wandb-metadata.json")).read())
        assert meta["state"] == "failed"
        assert meta["exitcode"] == 1


def test_dry_run_kill(runner):
    with runner.isolated_filesystem():
        with open("train.py", "w") as f:
            f.write(train_py.replace("#os.kill", "os.kill"))
        environ = {
            "WANDB_MODE": "dryrun",
            "WANDB_TEST": "true",
        }
        res = sh.python("train.py", epochs=10, _bg=True, _env=environ)
        try:
            res.wait()
            print(res)
        except sh.ErrorReturnCode:
            pass
        dirs = glob.glob(os.path.join("wandb", "dry*"))
        print(dirs)
        run_dir = dirs[0]
        meta = json.loads(
            open(os.path.join(run_dir, "wandb-metadata.json")).read())
        assert meta["state"] == "killed"
        assert meta["exitcode"] == 255
        assert meta["args"] == ["--epochs=10"]


@pytest.mark.skipif(sys.version_info < (3, 6), reason="Funky things in python 2 land and multiprocessing")
def test_mock_server_no_internet(runner):
    with runner.isolated_filesystem():
        with open("train.py", "w") as f:
            f.write(train_py)
        environ = {
            "WANDB_BASE_URL": "http://localhost:%i" % 10101,
            "WANDB_API_KEY": "a" * 40,
            "WANDB_HTTP_TIMEOUT": "1"
        }

        res = sh.python("train.py", epochs=10, _bg=True, _env=environ)
        stdout, stderr = "", ""
        try:
            time.sleep(5)  # TODO: this might not always be enough...
            res.kill()
            res.stdout
        except (sh.ErrorReturnCode, ProcessLookupError):  # noqa: F821
            pass
        stdout = res.stdout.decode("utf8")
        stderr = res.stderr.decode("utf8")
        print(res)
        if os.path.exists("wandb/debug.log"):
            print(open("wandb/debug.log").read())
        assert "Finished" in stdout
        assert "wandb: Network error" in stderr
        run_dir = glob.glob(os.path.join("wandb", "run*"))[0]
        meta = json.loads(
            open(os.path.join(run_dir, "wandb-metadata.json")).read())
        assert meta["state"] == "finished"


@pytest.mark.skipif(sys.version_info < (3, 6), reason="Funky things in python 2 land and multiprocessing")
def test_mock_server_with_internet(runner, live_mock_server):
    with runner.isolated_filesystem():
        with open("train.py", "w") as f:
            f.write(train_py)
        environ = {
            "WANDB_BASE_URL": "http://localhost:%i" % 8765,
            "WANDB_API_KEY": "a" * 40,
            "WANDB_HTTP_TIMEOUT": "1"
        }

        res = sh.python("train.py", epochs=10, _bg=True, _env=environ)
        stdout, stderr = "", ""
        try:
            res.wait()
        except (sh.ErrorReturnCode, ProcessLookupError):  # noqa: F821
            pass
        print(res)
        stdout = res.stdout.decode("utf8")
        stderr = res.stderr.decode("utf8")
        if os.path.exists("wandb/debug.log"):
            print(open("wandb/debug.log").read())
        assert "Finished" in stdout
        assert "wandb: Network error" not in stderr
        assert "wandb: Program ended successfully" in stderr
        run_dir = glob.glob(os.path.join("wandb", "run*"))[0]
        meta = json.loads(
            open(os.path.join(run_dir, "wandb-metadata.json")).read())
        assert meta["state"] == "finished"
