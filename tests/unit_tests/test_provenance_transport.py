import os
import sys
import tempfile
from types import SimpleNamespace


def test_level1_never_enables_or_creates_raw_nccl_logs(monkeypatch, tmp_path):
    from wandb.sdk.provenance import level1

    monkeypatch.delitem(sys.modules, "torch.distributed", raising=False)
    for name in ("NCCL_DEBUG", "NCCL_DEBUG_FILE", "NCCL_DEBUG_SUBSYS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "RANK": "0",
        "LOCAL_RANK": "0",
        "GROUP_RANK": "0",
        "WORLD_SIZE": "1",
        "WANDB_RUN_ID": "job",
    }.items():
        monkeypatch.setenv(name, value)
    capture = tmp_path / "capture"
    capture.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(capture))
    level1.install_level1_bootstrap()
    assert os.environ.get("NCCL_DEBUG") is None
    assert os.environ.get("NCCL_DEBUG_FILE") is None
    assert os.environ.get("NCCL_DEBUG_SUBSYS") is None
    assert list(capture.iterdir()) == []


def test_level1_reports_transport_unavailable_without_reading_user_log(
    monkeypatch, tmp_path
):
    from wandb.sdk.provenance.level1 import Level1Collectors, install_level1_bootstrap

    log = tmp_path / "user.log"
    original = "private-host NCCL INFO Using network GPUDirectTCPXO"
    log.write_text(original)
    monkeypatch.setenv("NCCL_DEBUG", "INFO")
    monkeypatch.setenv("NCCL_DEBUG_FILE", str(log))
    install_level1_bootstrap()
    events = []
    collector = Level1Collectors(
        SimpleNamespace(emit=lambda kind, payload: events.append((kind, payload)))
    )
    collector._communication("unavailable", [], 0)
    collector._communication("unavailable", [], 0)
    collector.close()
    transport = [
        payload for _, payload in events if payload.get("collector") == "nccl_transport"
    ]
    assert transport == [
        {
            "collector": "nccl_transport",
            "status": "unavailable",
            "reason": "bounded_source_unavailable",
        }
    ]
    assert not any(kind == "platform" for kind, _ in events)
    assert log.read_text() == original
    assert os.environ["NCCL_DEBUG_FILE"] == str(log)
