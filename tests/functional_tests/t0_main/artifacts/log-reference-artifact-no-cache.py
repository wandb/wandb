import tempfile

import wandb


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_name = "hello.txt"
        local_path = tmpdir + "/" + file_name
        with wandb.init() as run:
            artifact = wandb.Artifact("test-artifact-1", "test-type")
            with open(local_path, "w") as f:
                f.write("hello world")

            artifact.add_file(local_path, file_name)
            run.log_artifact(artifact)

        with wandb.init() as run:
            artifact = wandb.Artifact("test-artifact-2", "test-type")
            art1 = run.use_artifact("test-artifact-1:latest")
            local_entry = art1.get_path(file_name)
            local_ref_path = local_entry.ref_url()
            # Blow away cache
            # This ensures our references work without having pre-loaded cache
            from wandb.sdk.interface import artifacts

            artifacts._artifacts_cache = None
            # End blow away
            artifact.add_reference(local_ref_path)
            run.log_artifact(artifact)


if __name__ == "__main__":
    main()
