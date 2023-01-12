import tempfile

import wandb


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = tmpdir + "/hello.txt"
        with wandb.init() as run:
            artifact = wandb.Artifact("test-artifact", "test-type")
            with open(local_path, "w") as f:
                f.write("hello world")

            artifact.add_file(local_path)
            run.log_artifact(artifact)

        with wandb.init() as run:
            artifact = wandb.Artifact("test-artifact-2", "test-type")
            art1 = run.use_artifact("test-artifact:latest")
            local_entry = art1.get_path(local_path)
            local_ref_path = local_entry.ref_url()
            artifact.add_reference(local_ref_path)
            run.log_artifact(artifact)

        with wandb.init() as run:
            artifact = wandb.Artifact("test-artifact-3", "test-type")
            art1 = run.use_artifact("test-artifact:latest")
            local_entry = art1.get_path(local_path)
            local_ref_path = local_entry.ref_url()
            # Blow away cache
            # This ensures our references work without having pre-loaded cache
            from wandb.sdk.interface import artifacts

            artifacts._artifacts_cache = None
            # End blow away
            artifact.add_reference(local_ref_path)
            run.log_artifact(artifact)

        with wandb.init() as run:
            art1 = run.use_artifact("test-artifact-3:latest")
            art1.get_path(local_path).download()


if __name__ == "__main__":
    main()
