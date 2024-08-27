"""Test for run.link_artifact().

Allows user to link an artifact to a portfolio, without logging it first.
"""

import tempfile

import wandb
from wandb.errors import CommError


def main():
    with wandb.init() as run:
        wandb.log({"metric": 5})
        try:
            artifact = run.use_artifact("test-link-artifact:latest", "model")
        except CommError:
            artifact = wandb.Artifact("test-link-artifact", "model")
            with tempfile.TemporaryDirectory() as tmpdir:
                with open(tmpdir + "/boom.txt", "w") as f:
                    f.write("testing")
                local_path = f"{tmpdir}/boom.txt"
                artifact.add_file(local_path, "test-name")
            artifact = run.log_artifact(artifact)
            artifact.wait()
        run.link_artifact(artifact, "project/test_portfolio")


if __name__ == "__main__":
    main()
