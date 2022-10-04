import asyncio
import os
import platform
import tempfile

import wandb


async def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        with wandb.init() as run:
            wandb.log({"metric": 5})
            artifact = wandb.Artifact("test-artifact", "test-type")
            with open(tmpdir + "/boom.txt", "w") as f:
                f.write("testing")

            local_path = f"{tmpdir}/boom.txt"
            artifact.add_file(local_path, "test-name")
            run.log_artifact(artifact)

        with wandb.init() as run:
            art = run.use_artifact("test-artifact:latest")
            fut = art.download_async()
            if platform.system() == "Windows":
                part = "test-artifact-v0"
            else:
                part = "test-artifact:v0"
            path = await fut
            assert path == os.path.join(".", "artifacts", part)


if __name__ == "__main__":
    asyncio.run(main)
