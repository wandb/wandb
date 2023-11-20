import os
import platform
import traceback

import pytest
from wandb.cli import cli


@pytest.mark.nexus_failure(feature="artifacts")
@pytest.mark.skipif(platform.system() == "Windows", reason="TODO: fix on windows")
def test_artifact_download(runner, git_repo, mock_server, mocked_run):
    result = runner.invoke(cli.artifact, ["get", "test/mnist:v0"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Downloading dataset artifact" in result.output
    path = os.path.join(".", "artifacts", "mnist:v0")
    if platform.system() == "Windows":
        head, tail = os.path.splitdrive(path)
        path = head + tail.replace(":", "-")
    assert "Artifact downloaded to %s" % os.path.abspath(path) in result.output
    assert os.path.exists(path)


@pytest.mark.nexus_failure(feature="artifacts")
def test_artifact_upload(runner, git_repo, mock_server, mocked_run):
    with open("artifact.txt", "w") as f:
        f.write("My Artifact")
    result = runner.invoke(cli.artifact, ["put", "artifact.txt", "-n", "test/simple"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "Uploading file artifact.txt to:" in result.output
    assert "FAKE_ENTITY/FAKE_PROJECT/mnist:v0" in result.output


def test_artifact_ls(runner, git_repo, mock_server):
    result = runner.invoke(cli.artifact, ["ls", "test"])
    print(result.output)
    print(result.exception)
    print(traceback.print_tb(result.exc_info[2]))
    assert result.exit_code == 0
    assert "81.3KB" in result.output
    assert "mnist:v2" in result.output
