import hashlib
from datetime import datetime
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory

import wandb

wandb.require("core")


with TemporaryDirectory() as tmp_dir:
    for i in range(30000):
        f = Path(tmp_dir) / f"file_{i:03}.txt"
        f.write_bytes(hashlib.sha256(str(i).encode()).digest())

    with wandb.init(project="benchmark-artifact-upload") as run:
        start_time = datetime.now()
        artifact = wandb.Artifact(f"benchmark-artifact-{token_hex(8)}", "test")
        artifact.add_dir(tmp_dir)
        run.log_artifact(artifact)
        artifact.wait()
        end_time = datetime.now()
        print(f"Uploaded artifact in {end_time - start_time} seconds")
