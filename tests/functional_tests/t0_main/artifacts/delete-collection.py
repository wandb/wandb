"""Test for collection.delete().

Deleting a portfolio should unlink artifacts from it, while deleting a sequence should
delete all artifacts under it.
"""
import tempfile

import wandb


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        with wandb.init() as run:
            project_name = f"{run.entity}/{run.project}"
            artifact = wandb.Artifact("test-artifact", "dummy")
            with artifact.new_file(tmpdir + "/foo.txt", "w") as f:
                f.write("testing")
            run.log_artifact(artifact)
            run.link_artifact(artifact, "test-portfolio")

    api = wandb.Api()
    project = api.artifact_type("dummy", project=project_name)

    portfolio = project.collection("test-portfolio")
    portfolio.delete()

    sequence = project.collection("test-artifact")
    sequence.delete()


if __name__ == "__main__":
    main()
