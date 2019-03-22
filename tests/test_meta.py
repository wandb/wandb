import pytest
from .utils import git_repo
import os
import glob
import sys
import six
from wandb.meta import Meta
from wandb.apis import InternalApi


def test_meta(git_repo):
    sys.argv = ["foo", "bar"]
    meta = Meta(InternalApi())
    print(meta.data)
    assert meta.data["cpu_count"] > 0
    assert meta.data["git"]["commit"]
    assert meta.data["heartbeatAt"]
    assert meta.data["startedAt"]
    assert meta.data["host"]
    assert meta.data["root"] == os.getcwd()
    assert meta.data["python"]
    assert meta.data["program"]
    assert meta.data["args"] == ["bar"]
    assert meta.data["state"] == "running"
    assert meta.data["username"]
    assert meta.data["os"]


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
