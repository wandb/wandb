import http.server
import threading
from types import SimpleNamespace

import pytest
from wandb.sdk.provenance.platform import oci


@pytest.fixture
def imds():
    requests = []
    pools = {"/opc/v2/instance/instancePoolId": b"ocid1.instancepool.private"}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            body = pools.get(self.path)
            self.send_response(200 if body else 404)
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/opc/v2", requests, pools
    server.shutdown()


@pytest.fixture
def credentials(tmp_path, monkeypatch):
    for name in ("OCI_CLI_AUTH", "OCI_CLI_CONFIG_FILE", "OCI_CONFIG_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / "oci-config"
    config.write_text("[DEFAULT]\n")
    return config


def _sdk(calls, error=None):
    class Client:
        def __init__(self, config, **kwargs):
            calls.append(("client", config, sorted(kwargs)))

        def get_instance_pool(self, pool):
            calls.append(("get_instance_pool", pool))
            if error is not None:
                raise error

    return SimpleNamespace(
        config=SimpleNamespace(from_file=lambda file_location: {"file": file_location}),
        core=SimpleNamespace(ComputeManagementClient=Client),
        retry=SimpleNamespace(NoneRetryStrategy=lambda: "no-retry"),
        auth=SimpleNamespace(
            signers=SimpleNamespace(
                InstancePrincipalsSecurityTokenSigner=lambda: "signer"
            )
        ),
    )


def test_missing_sdk_or_credentials_makes_no_request(imds, credentials, monkeypatch):
    url, requests, _ = imds
    monkeypatch.setattr(oci.importlib.util, "find_spec", lambda name: None)
    assert oci.collect(url)["reason"] == "missing_dependency"
    assert oci.collect(url, _sdk([]))["reason"] == "missing_credentials"
    assert requests == []


def test_mounted_config_queries_only_current_instance_pool(
    imds, credentials, monkeypatch
):
    url, requests, _ = imds
    monkeypatch.setenv("OCI_CLI_CONFIG_FILE", str(credentials))
    calls = []
    assert oci.collect(url, _sdk(calls)) == {
        "collector": "oci_instance_pool",
        "status": "available",
        "source": "get_instance_pool",
        "topology_value": "ocid1.instancepool.private",
    }
    assert requests == [("/opc/v2/instance/instancePoolId", "Bearer Oracle")]
    assert calls == [
        ("client", {"file": str(credentials)}, ["retry_strategy", "timeout"]),
        ("get_instance_pool", "ocid1.instancepool.private"),
    ]


def test_instance_principal_uses_signer(imds, credentials, monkeypatch):
    url, _, _ = imds
    monkeypatch.setenv("OCI_CLI_AUTH", "instance_principal")
    calls = []
    assert oci.collect(url, _sdk(calls))["status"] == "available"
    assert calls[0] == ("client", {}, ["retry_strategy", "signer", "timeout"])


def test_permission_denial_and_missing_pool_are_explicit(
    imds, credentials, monkeypatch
):
    url, _, pools = imds
    monkeypatch.setenv("OCI_CONFIG_FILE", str(credentials))
    denied = Exception("NotAuthorizedOrNotFound")
    denied.status = 404
    result = oci.collect(url, _sdk([], denied))
    assert result == {
        "collector": "oci_instance_pool",
        "status": "permission_denied",
        "reason": "permission_denied",
    }
    pools.clear()
    calls = []
    assert oci.collect(url, _sdk(calls))["reason"] == "not_in_instance_pool"
    assert calls == []


def test_unreachable_metadata_is_bounded(credentials, monkeypatch):
    import time

    monkeypatch.setenv("OCI_CONFIG_FILE", str(credentials))
    started = time.monotonic()
    assert (
        oci.collect("http://127.0.0.1:9", _sdk([]))["reason"] == "metadata_unavailable"
    )
    assert time.monotonic() - started < 3


def test_enrich_selects_oci_only_from_chassis_asset_tag(tmp_path, monkeypatch):
    from wandb.sdk.provenance import platform

    monkeypatch.delenv("WANDB_X_PROVENANCE_PROVIDER", raising=False)
    monkeypatch.setattr(oci, "collect", lambda: {"collector": "oci_instance_pool"})
    emitted = []
    emitter = SimpleNamespace(
        emit=lambda kind, payload: emitted.append((kind, payload))
    )
    for name, files in {
        "oci": {
            "chassis_asset_tag": "OracleCloud.com",
            "sys_vendor": "Oracle Corporation",
        },
        "vendor": {"sys_vendor": "Oracle Corporation"},
    }.items():
        for file, value in files.items():
            path = tmp_path / name / "class/dmi/id" / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
    mlx5 = tmp_path / "vendor/class/infiniband/mlx5_0/ports/1"
    mlx5.mkdir(parents=True)
    (mlx5 / "link_layer").write_text("Ethernet\n")
    platform.enrich(emitter, str(tmp_path / "oci"))
    platform.enrich(emitter, str(tmp_path / "vendor"))
    assert emitted == [("capability", {"collector": "oci_instance_pool"})]
