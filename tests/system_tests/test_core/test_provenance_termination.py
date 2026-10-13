import gzip
import json
import os
import signal
import subprocess
import sys
import time

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal behavior")
def test_sigterm_seals_offline_provenance_and_preserves_exit_status(tmp_path):
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("WANDB_")
    }
    env["WANDB_DIR"] = str(tmp_path)
    code = """import json,os,signal,time
import wandb
from wandb.sdk import wandb_setup
run=wandb.init(mode='offline',settings=wandb.Settings(x_provenance_level=0))
from wandb.proto import wandb_internal_pb2 as pb
response=run._interface.deliver_provenance_start(pb.ProvenanceStartRequest(protocol_version=2,run_id=run.id,primary=True,identity_json=b'{}')).wait_or(timeout=5)
assert response.accepted
run._interface.publish_provenance_record(pb.ProvenanceRecord(kind='step',payload_json=b'{"step":7}',monotonic_ns=1,wall_time_ns=time.time_ns()))
run._interface.deliver_get_summary().wait_or(timeout=5)
print(run.settings.files_dir,flush=True)
process=wandb_setup.singleton()._connection._proc._process
os.kill(process.pid,signal.SIGTERM)
process.wait(timeout=10)
os._exit(23)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 23, result.stderr
    manifests = list(tmp_path.rglob("wandb-telemetry/v2/manifest/*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert manifest["finalized"] is True
    assert manifest["exit"] == {"code": 143, "reason": "terminated"}
    chunks = list(tmp_path.rglob("wandb-telemetry/v2/chunks/*/*.jsonl.gz"))
    records = [
        json.loads(line)
        for chunk in chunks
        for line in gzip.decompress(chunk.read_bytes()).splitlines()
    ]
    assert any(record["kind"] == "step" and record["step"] == 7 for record in records)


_SIGTERM_CODE = """import os,signal
import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk import wandb_setup
run=wandb.init(id={run_id!r},settings=wandb.Settings(x_provenance_level={level}))
if {level} is not None:
    request=pb.ProvenanceStartRequest(protocol_version=2,run_id=run.id,primary=True)
    assert run._interface.deliver_provenance_start(request).wait_or(timeout=5).accepted
run.log({{'x':1}})
run._interface.deliver_get_summary().wait_or(timeout=5)
process=wandb_setup.singleton()._connection._proc._process
os.kill(process.pid,signal.SIGTERM)
process.wait(timeout=15)
os._exit(0)
"""


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal behavior")
@pytest.mark.parametrize("level", [None, 0])
def test_sigterm_never_reports_success(wandb_backend_spy, tmp_path, level):
    run_id = f"sigterm-{level}"
    env = dict(os.environ, WANDB_DIR=str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-c", _SIGTERM_CODE.format(run_id=run_id, level=level)],
        env=env,
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stderr
    with wandb_backend_spy.freeze() as snapshot:
        exit_code = snapshot.exit_code(run_id=run_id)
        files = snapshot.uploaded_files(run_id=run_id)
    if level is None:
        assert exit_code is None
    else:
        assert exit_code == 143
        assert any(name.startswith("wandb-telemetry/v2/manifest/") for name in files)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal behavior")
@pytest.mark.parametrize("victim", ["worker", "core"])
def test_hard_kill_preserves_only_available_finalization(tmp_path, victim):
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("WANDB_")
    }
    env["WANDB_DIR"] = str(tmp_path)
    code = """import json,os,signal,time
import wandb
from wandb.sdk import wandb_setup
run=wandb.init(mode='offline',settings=wandb.Settings(x_provenance_level=0))
from wandb.proto import wandb_internal_pb2 as pb
response=run._interface.deliver_provenance_start(pb.ProvenanceStartRequest(protocol_version=2,run_id=run.id,primary=True,identity_json=b'{}')).wait_or(timeout=5)
assert response.accepted
run._interface.publish_provenance_record(pb.ProvenanceRecord(kind='step',payload_json=b'{"step":7}',monotonic_ns=1,wall_time_ns=time.time_ns()))
run._interface.deliver_get_summary().wait_or(timeout=5)
print(wandb_setup.singleton()._connection._proc._process.pid,flush=True)
signal.pause()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    core_pid = None
    try:
        core_pid = int(process.stdout.readline().strip())
        manifests = list(tmp_path.rglob("wandb-telemetry/v2/manifest/*.json"))
        assert len(manifests) == 1
        original = manifests[0].read_bytes()
        os.kill(process.pid if victim == "worker" else core_pid, signal.SIGKILL)
        if victim == "worker":
            assert process.wait(timeout=5) == -signal.SIGKILL
            deadline = time.monotonic() + 10
            while not json.loads(manifests[0].read_text()).get("finalized"):
                assert time.monotonic() < deadline
                time.sleep(0.05)
            chunks = list(tmp_path.rglob("wandb-telemetry/v2/chunks/*/*.jsonl.gz"))
            assert any(
                b'"step":7' in gzip.decompress(path.read_bytes()) for path in chunks
            )
        else:
            assert manifests[0].read_bytes() == original
            assert not json.loads(original).get("finalized", False)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        if core_pid is not None:
            try:
                os.kill(core_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
