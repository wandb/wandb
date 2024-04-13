import hashlib
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory

import wandb

wandb.require("core")


def test_benchmark_artifact_upload(benchmark):
    with TemporaryDirectory() as tmp_dir:
        for i in range(1000):
            f = Path(tmp_dir) / f"file_{i:03}.txt"
            f.write_bytes(hashlib.sha256(str(i).encode()).digest())

        def upload_artifact(run):
            artifact = wandb.Artifact(f"benchmark-artifact-{token_hex(8)}", "test")
            artifact.add_dir(tmp_dir)
            run.log_artifact(artifact)
            artifact.wait()

        with wandb.init(project="benchmark-artifact-upload") as run:
            benchmark(upload_artifact, run)
