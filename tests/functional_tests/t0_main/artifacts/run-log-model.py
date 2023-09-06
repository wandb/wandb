import tempfile

import wandb


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        with wandb.init() as run:
            wandb.log({"metric": 5})
            with open(tmpdir + "/boom.txt", "w") as f:
                f.write("testing")

            local_path = f"{tmpdir}/boom.txt"
            run.log_model(local_path, model_name="test-model")


if __name__ == "__main__":
    main()
