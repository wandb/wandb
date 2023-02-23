"""Test for run.link_artifact().

Allows user to link an artifact to a portfolio, without logging it first.
"""
import tempfile

import wandb


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        with wandb.init() as run:
            wandb.log({"metric": 5})
            artifact = wandb.Artifact("test-artifact", "model")
            with open(tmpdir + "/boom.txt", "w") as f:
                f.write("testing")

            local_path = f"{tmpdir}/boom.txt"
            artifact.add_file(local_path, "test-name")
            run.link_artifact(artifact, "entity/project/test_portfolio")


if __name__ == "__main__":
    main()
