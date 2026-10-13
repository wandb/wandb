import os
import sys
import tempfile
from types import SimpleNamespace

import pytest


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


def _maps(tmp_path, *paths):
    lines = [
        f"7f00-7f01 r-xp 00000000 08:01 {index} {path}"
        for index, path in enumerate(paths)
    ]
    maps = tmp_path / "maps"
    maps.write_text("\n".join(["7f00-7f01 rw-p 00000000 00:00 0", *lines]) + "\n")
    return str(maps)


def _transport(monkeypatch, maps, env, ib_devices=()):
    from wandb.sdk.provenance import level1

    ib_class = os.path.join(os.path.dirname(maps), "infiniband")
    os.makedirs(ib_class, exist_ok=True)
    for name in os.listdir(ib_class):
        os.rmdir(os.path.join(ib_class, name))
    for name in ib_devices:
        os.mkdir(os.path.join(ib_class, name))
    monkeypatch.setattr(level1, "_IB_CLASS", ib_class)

    for name in list(os.environ):
        if name.startswith("NCCL_"):
            monkeypatch.delenv(name)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(level1, "_MAPS", maps)
    events = []
    collector = level1.Level1Collectors(
        SimpleNamespace(emit=lambda kind, payload: events.append((kind, payload)))
    )
    collector._transport()
    return next(p for _, p in events if p.get("collector") == "nccl_transport")


def test_transport_is_configured_and_loaded_evidence_without_paths(
    monkeypatch, tmp_path
):
    maps = _maps(
        tmp_path,
        "/opt/venv/lib/python3.12/site-packages/nvidia/nccl/lib/libnccl.so.2",
        "/usr/local/tcpx/lib64/libnccl-net.so",
    )
    payload = _transport(
        monkeypatch,
        maps,
        {
            "NCCL_GPUDIRECTTCPX_SOCKET_IFNAME": "eth1,eth2",
            "NCCL_GPUDIRECTTCPX_FORCE_ACK": "0",
            "NCCL_GPUDIRECTTCPX_UNIX_CLIENT_PREFIX": "/run/tcpx",
            "NCCL_SOCKET_IFNAME": "eth0",
            "NCCL_DEBUG_FILE": "/home/user/nccl.log",
        },
    )
    assert payload == {
        "collector": "nccl_transport",
        "status": "partial",
        "source": "proc_maps+nccl_env",
        "configured": "tcpx",
        "loaded": "tcpx",
        "transport": "tcpx",
        "confidence": "configured_and_loaded",
        "reason": "configured_and_loaded",
        "nccl_env": {
            "NCCL_GPUDIRECTTCPX_FORCE_ACK": "0",
            "NCCL_GPUDIRECTTCPX_SOCKET_IFNAME": "set",
            "NCCL_GPUDIRECTTCPX_UNIX_CLIENT_PREFIX": "set",
        },
    }
    text = repr(payload)
    for private in ("eth", "/usr", "/run", "/home", "/opt"):
        assert private not in text


def test_transport_reports_socket_fallback_and_plugin_mismatch(monkeypatch, tmp_path):
    nccl = "/x/nvidia/nccl/lib/libnccl.so.2"
    socket = _transport(monkeypatch, _maps(tmp_path, nccl), {})
    assert (socket["transport"], socket["confidence"], socket["reason"]) == (
        "socket",
        "loaded",
        "loaded_only",
    )
    fallback = _transport(monkeypatch, _maps(tmp_path, nccl), {"NCCL_NET": "FasTrak"})
    assert (fallback["configured"], fallback["transport"], fallback["reason"]) == (
        "tcpxo",
        "socket",
        "configured_not_loaded",
    )
    assert fallback["nccl_env"] == {"NCCL_NET": "tcpxo"}
    efa = _transport(
        monkeypatch,
        _maps(tmp_path, nccl, "/opt/amazon/ofi-nccl/lib/libnccl-net-ofi.so"),
        {"NCCL_NET_PLUGIN": "/opt/amazon/ofi-nccl/lib/libnccl-net-ofi.so"},
    )
    assert (efa["transport"], efa["nccl_env"]) == ("efa", {"NCCL_NET_PLUGIN": "efa"})
    missing = _transport(monkeypatch, str(tmp_path / "absent"), {})
    assert (missing["status"], missing["reason"]) == ("unavailable", "no_evidence")


def test_transport_maps_read_is_capped(monkeypatch, tmp_path):
    from wandb.sdk.provenance import level1

    monkeypatch.setattr(level1, "_MAPS_LIMIT", 64)
    nccl = "/x/nvidia/nccl/lib/libnccl.so.2"
    payload = _transport(monkeypatch, _maps(tmp_path, *([nccl] * 8)), {})
    assert (payload["status"], payload["reason"]) == ("unavailable", "maps_truncated")


@pytest.mark.parametrize(
    "libraries, env, ib_devices, transport",
    [
        (["libibverbs.so.1", "libmlx5.so.1"], {}, (), "socket"),
        (["libibverbs.so.1"], {}, ("mlx5_0",), "ib"),
        (["libibverbs.so.1"], {"NCCL_IB_DISABLE": "1"}, ("mlx5_0",), "socket"),
        (["gib/lib64/libnccl-net_internal.so"], {}, (), "ib"),
        (["libnccl-net-ib.so"], {}, (), "ib"),
        (["tcpx/lib64/libnccl-net.so"], {}, (), "tcpx"),
        (["tcpxo/lib64/libnccl-net.so"], {}, (), "tcpxo"),
        (["fastrak/lib64/libnccl-net.so"], {}, (), "tcpxo"),
        (["ofi-nccl/lib/libnccl-net-ofi.so", "libfabric.so.1"], {}, ("rdmap0",), "efa"),
        (["libfabric.so.1", "libefa.so.1"], {}, (), "socket"),
    ],
)
def test_transport_family_comes_from_plugins_and_rdma_devices(
    monkeypatch, tmp_path, libraries, env, ib_devices, transport
):
    paths = ["/x/nvidia/nccl/lib/libnccl.so.2", *(f"/opt/{lib}" for lib in libraries)]
    payload = _transport(monkeypatch, _maps(tmp_path, *paths), env, ib_devices)
    assert (payload["loaded"], payload["transport"]) == (transport, transport)
    assert "mlx5_0" not in repr(payload) and "rdmap0" not in repr(payload)
