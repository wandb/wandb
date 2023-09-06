"""Test for run.link_model().

Allows user to link a model artifact to a portfolio, without logging it first.
"""
import tempfile

import wandb


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        with wandb.init() as run:
            wandb.log({"metric": 5})
            with open(tmpdir + "/boom.txt", "w") as f:
                f.write("testing")

            local_path = f"{tmpdir}/boom.txt"
            # artifact = wandb.Artifact("test-model", "model")
            # artifact.add_file(local_path, "test-name")
            # run.log_artifact(artifact)
            run.link_model(local_path, "test_portfolio", "test_model")


if __name__ == "__main__":
    main()
