import wandb
import tempfile


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        with wandb.init() as run:
            wandb.log({"metric": 5})
            artifact = wandb.Artifact("test-artifact", "test-type")
            with open(tmpdir + "/boom.txt", "w") as f:
                f.write("testing")

            local_path = f"{tmpdir}/boom.txt"
            artifact.add_file(local_path, "test-name")
            run.log_artifact(artifact)


if __name__ == "__main__":
    main()
