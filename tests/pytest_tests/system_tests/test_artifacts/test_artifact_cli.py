import os
import platform

from wandb.cli import cli


def test_artifact(runner, user):
    # wandb artifact put
    with open("artifact.txt", "w") as f:
        f.write("My Artifact")
    result = runner.invoke(cli.artifact, ["put", "artifact.txt", "-n", "test/simple"])
    assert result.exit_code == 0
    assert "Uploading file artifact.txt to:" in result.output
    assert "test/simple:v0" in result.output

    # wandb artifact ls
    result = runner.invoke(cli.artifact, ["ls", "test"])
    assert result.exit_code == 0
    assert "11.0B" in result.output
    assert "simple:v0" in result.output

    # wandb artifact get
    result = runner.invoke(cli.artifact, ["get", "test/simple:v0"])
    assert result.exit_code == 0
    assert "Downloading dataset artifact" in result.output
    path = os.path.join(".", "artifacts", "simple:v0")
    if platform.system() == "Windows":
        head, tail = os.path.splitdrive(path)
        path = head + tail.replace(":", "-")
    assert "Artifact downloaded to %s" % os.path.abspath(path) in result.output
    assert os.path.exists(path)
