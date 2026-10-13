import json
import os
import subprocess
import sys

import wandb


def test_interpreter_bootstrap_shared_ranks(wandb_backend_spy, tmp_path):
    from wandb.sdk.provenance import startup

    (tmp_path / startup.PTH_NAME).write_text(startup.PTH_LINE)
    run_id = "provenance-shared-ranks"
    writers = []
    for rank in (0, 1):
        env = dict(
            os.environ,
            WANDB_X_PROVENANCE_LEVEL="0",
            WANDB_RUN_ID=run_id,
            RANK=str(rank),
            LOCAL_RANK=str(rank),
            GROUP_RANK="0",
            WORLD_SIZE="2",
            WANDB_DIR=str(tmp_path),
            WANDB_PROJECT="provenance-bootstrap",
        )
        store = (tmp_path / f"store-{rank}").as_uri()
        code = f"""import site,json
site.addsitedir({str(tmp_path)!r})
import wandb
import torch.distributed as dist
from wandb.sdk.provenance import bootstrap
assert wandb.run is None
dist.init_process_group('gloo', init_method={store!r}, rank=0, world_size=1)
assert bootstrap.state == bootstrap.BootstrapState.ACTIVE, bootstrap.state
run=wandb.run
assert wandb.init(id={run_id!r}) is run
bootstrap.emitter.emit('step',{{'step':1}})
writer=bootstrap.emitter.writer_id
run.finish()
print(json.dumps({{'id':run.id,'writer':writer,'label':run.settings.x_label,'primary':run.settings.x_primary}}))
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout.strip().splitlines()[-1])
        assert output["id"] == run_id
        assert output["label"] == f"rank{rank}"
        assert output["primary"] is (rank == 0)
        writers.append(output["writer"])
    assert writers[0] != writers[1]
    with wandb_backend_spy.freeze() as snapshot:
        files = snapshot.uploaded_files(run_id=run_id)
    assert all(
        f"wandb-telemetry/v2/manifest/{writer}.json" in files for writer in writers
    )
    # Rank 1 finished after primary rank 0, so its last request must not reopen the run.
    api_run = wandb.Api().run(
        f"{os.environ['WANDB_ENTITY']}/provenance-bootstrap/{run_id}"
    )
    assert api_run.state == "finished"
