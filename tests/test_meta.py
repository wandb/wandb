import pytest
from .utils import git_repo
import os
import glob
import sys
import six
from click.testing import CliRunner
import wandb
import types
import subprocess
from wandb import env
from wandb.meta import Meta
from wandb.apis import InternalApi


def test_meta(git_repo, mocker):
    mocker.patch.object(sys, 'argv', ["foo", "bar"])
    meta = Meta(InternalApi())
    meta.write()
    print(meta.data)
    assert meta.data["cpu_count"] > 0
    assert meta.data["git"]["commit"]
    assert meta.data["heartbeatAt"]
    assert meta.data["startedAt"]
    assert meta.data["host"]
    assert meta.data["root"] == os.getcwd()
    assert meta.data["python"]
    assert meta.data["program"]
    assert meta.data["executable"]
    assert meta.data["args"] == ["bar"]
    assert meta.data["state"] == "running"
    assert meta.data["username"]
    assert meta.data["os"]

def test_disable_code(git_repo):
    os.environ[env.DISABLE_CODE] = "true"
    meta = Meta(InternalApi())
    assert meta.data.get("git") is None
    del os.environ[env.DISABLE_CODE]


def test_colab(mocker, monkeypatch):
    with CliRunner().isolated_filesystem():
        mocker.patch('wandb._get_python_type', lambda: "jupyter")
        with open("test.ipynb", "w") as f:
            f.write("{}")
        module = types.ModuleType("fake_jupyter")
        module.notebook_metadata = lambda: {"path": "fileId=123abc", "name": "test.ipynb", "root": os.getcwd()}
        monkeypatch.setattr(wandb, 'jupyter', module)
        meta = Meta(InternalApi())
        assert meta.data["colab"] == "https://colab.research.google.com/drive/123abc"
        assert meta.data["program"] == "test.ipynb"
        assert meta.data["codeSaved"]
        assert os.path.exists("code/test.ipynb")

def test_git_untracked_notebook_env(monkeypatch, git_repo, mocker):
    mocker.patch('wandb._get_python_type', lambda: "jupyter")
    with open("test.ipynb", "w") as f:
        f.write("{}")
    os.environ[env.NOTEBOOK_NAME] = "test.ipynb"
    meta = Meta(InternalApi())
    assert meta.data["program"] == "test.ipynb"
    assert meta.data["codeSaved"]
    assert os.path.exists("code/test.ipynb")
    os.environ[env.NOTEBOOK_NAME]

def test_git_tracked_notebook_env(monkeypatch, git_repo, mocker):
    mocker.patch('wandb._get_python_type', lambda: "jupyter")
    with open("test.ipynb", "w") as f:
        f.write("{}")
    subprocess.check_call(['git', 'add', 'test.ipynb'])
    os.environ[env.NOTEBOOK_NAME] = "test.ipynb"
    meta = Meta(InternalApi())
    assert meta.data["program"] == "test.ipynb"
    assert not meta.data.get("codeSaved")
    assert not os.path.exists("code/test.ipynb")
    os.environ[env.NOTEBOOK_NAME]

def test_meta_cuda(mocker):
    mocker.patch('wandb.meta.os.path.exists', lambda path: True)

    def magic(path, mode="w"):
        if "cuda/version.txt" in path:
            return six.StringIO("CUDA Version 9.0.176")
        else:
            return open(path, mode=mode)
    mocker.patch('wandb.meta.open', magic)
    meta = Meta(InternalApi())
    meta.data["cuda"] == "9.0.176"


def test_meta_thread(git_repo):
    meta = Meta(InternalApi(), "wandb")
    meta.start()
    meta.shutdown()
    print("GO", glob.glob("**"))
    assert os.path.exists("wandb/wandb-metadata.json")
