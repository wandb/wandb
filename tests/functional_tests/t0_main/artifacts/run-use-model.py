import tempfile
import os

import wandb


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        with wandb.init() as run:
            wandb.log({"metric": 5})
            with open(tmpdir + "/boom.txt", "w") as f:
                f.write("testing")

            local_path = f"{tmpdir}/boom.txt"
            logged_artifact = run.log_artifact(
                local_path, name="test-model", type="model"
            )
            logged_artifact.wait()
            download_path = run.use_model("test-model:v0")
            files = sorted(os.listdir(download_path))
            assert files[0] == "/boom.txt"


if __name__ == "__main__":
    main()
