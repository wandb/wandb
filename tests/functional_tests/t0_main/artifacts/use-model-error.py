import tempfile

import wandb
from wandb.beta.workflows import use_model


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        with wandb.init() as run:
            wandb.log({"metric": 5})
            artifact = wandb.Artifact("test-artifact", "test-type")
            with open(tmpdir + "/boom.txt", "w") as f:
                f.write("testing")

            local_path = f"{tmpdir}/boom.txt"
            artifact.add_file(local_path, "boom/test-name")
            artifact = run.log_artifact(artifact)
            artifact.wait()

            _ = use_model("test-artifact:latest")


if __name__ == "__main__":
    main()
