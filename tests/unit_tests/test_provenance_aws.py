import http.server
import threading
from types import SimpleNamespace

import pytest
from wandb.sdk.provenance.platform import aws

_TOPOLOGY = b"""<DescribeInstanceTopologyResponse xmlns="http://ec2.amazonaws.com/doc/2016-11-15/">
<requestId>r</requestId><instanceSet><item><instanceId>i-0raw</instanceId>
<instanceType>p5.48xlarge</instanceType><networkNodeSet><item>nn-1</item><item>nn-2</item>
<item>nn-private-3</item></networkNodeSet></item></instanceSet></DescribeInstanceTopologyResponse>"""
_DENIED = b"""<Response><Errors><Error><Code>UnauthorizedOperation</Code><Message>no</Message>
</Error></Errors><RequestID>r</RequestID></Response>"""


@pytest.fixture
def imds():
    requests = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_PUT(self):
            requests.append(
                (
                    "PUT",
                    self.path,
                    self.headers.get("X-aws-ec2-metadata-token-ttl-seconds"),
                )
            )
            self._reply(b"token-private")

        def do_GET(self):
            requests.append(
                ("GET", self.path, self.headers.get("X-aws-ec2-metadata-token"))
            )
            values = {
                "/latest/meta-data/instance-id": b"i-0raw",
                "/latest/meta-data/placement/region": b"us-east-1",
            }
            self._reply(values.get(self.path, b""), 200 if self.path in values else 404)

        def _reply(self, body, status=200):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", requests
    server.shutdown()


def _session(status, body, calls):
    import botocore.awsrequest
    import botocore.session

    session = botocore.session.Session()
    session.set_credentials("AKIDTEST", "secret-test")

    class Raw:
        def stream(self, **_):
            yield body

    def send(request, **_):
        calls.append(request.body)
        return botocore.awsrequest.AWSResponse(request.url, status, {}, Raw())

    session.register("before-send.ec2.DescribeInstanceTopology", send)
    return session


def test_missing_botocore_makes_no_metadata_request(imds, monkeypatch):
    url, requests = imds
    monkeypatch.setattr(aws.importlib.util, "find_spec", lambda name: None)
    assert aws.collect(url) == {
        "collector": "aws_instance_topology",
        "status": "unavailable",
        "reason": "missing_dependency",
    }
    assert requests == []


def test_topology_queries_only_current_instance_and_reports_nearest_node(imds):
    url, requests = imds
    calls = []
    result = aws.collect(url, _session(200, _TOPOLOGY, calls))
    assert result == {
        "collector": "aws_instance_topology",
        "status": "available",
        "source": "describe_instance_topology",
        "topology_value": "nn-private-3",
    }
    assert requests[0] == ("PUT", "/latest/api/token", "60")
    assert {token for method, _, token in requests[1:]} == {"token-private"}
    assert len(calls) == 1
    assert "InstanceId.1=i-0raw" in calls[0] and "InstanceId.2" not in calls[0]


def test_permission_denial_is_a_capability_gap(imds):
    url, _ = imds
    calls = []
    result = aws.collect(url, _session(403, _DENIED, calls))
    assert result["status"] == "permission_denied"
    assert "topology_value" not in result
    assert len(calls) == 1


def test_missing_credentials_makes_no_api_call(imds):
    url, _ = imds
    session = SimpleNamespace(
        get_credentials=lambda: None,
        create_client=lambda *a, **k: pytest.fail("no client without credentials"),
    )
    assert aws.collect(url, session)["reason"] == "missing_credentials"


def test_unreachable_metadata_is_bounded_and_explicit():
    import time

    started = time.monotonic()
    result = aws.collect("http://127.0.0.1:9", SimpleNamespace())
    assert time.monotonic() - started < 3
    assert result["reason"] == "metadata_unavailable"


def test_emitter_pseudonymizes_network_node(monkeypatch):
    from wandb.sdk.provenance.events import EventEmitter

    published = []
    monkeypatch.setenv("WANDB_X_PROVENANCE_REDACTION_KEY", "ab" * 32)
    emitter = EventEmitter(
        SimpleNamespace(publish_provenance_record=published.append), "writer"
    )
    emitter.emit(
        "capability",
        {
            "collector": "aws_instance_topology",
            "status": "available",
            "topology_value": "nn-private-3",
        },
    )
    emitter.close()
    payload = published[0].payload_json
    assert b"nn-private-3" not in payload
    assert b'"topology_value_hmac":"topology_value_' in payload


def _dmi(tmp_path, **values):
    for name, value in values.items():
        path = tmp_path / "class/dmi/id" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n")
    return str(tmp_path)


def test_enrich_runs_only_for_unambiguous_aws_evidence(tmp_path, monkeypatch):
    from wandb.sdk.provenance import platform

    monkeypatch.delenv("WANDB_X_PROVENANCE_PROVIDER", raising=False)
    monkeypatch.setattr(aws, "collect", lambda: {"collector": "aws_instance_topology"})
    emitted = []
    emitter = SimpleNamespace(emit=lambda kind, payload: emitted.append(payload))
    platform.enrich(emitter, _dmi(tmp_path / "aws", sys_vendor="Amazon EC2"))
    assert emitted == [{"collector": "aws_instance_topology"}]
    conflict = _dmi(tmp_path / "c", sys_vendor="Amazon EC2", product_name="Google")
    platform.enrich(emitter, conflict)
    efa_only = tmp_path / "efa/class/infiniband/rdmap79s0/device"
    efa_only.mkdir(parents=True)
    (efa_only / "vendor").write_text("0x1d0f\n")
    platform.enrich(emitter, str(tmp_path / "efa"))
    assert len(emitted) == 1


@pytest.mark.parametrize("level", [0, 1])
def test_attach_starts_platform_enrichment_only_at_level_1(monkeypatch, level):
    from wandb.sdk.provenance import bootstrap, platform, plugins

    started = threading.Event()
    monkeypatch.setattr(platform, "enrich", lambda emitter: started.set())
    monkeypatch.setattr(plugins, "load_test_plugins", lambda *a: None)
    monkeypatch.setattr(bootstrap, "_after_import", lambda: None)
    for name, value in {
        "_attached": None,
        "_installed": True,
        "_hook_seen": False,
        "level": None,
        "state": bootstrap.BootstrapState.DISABLED,
    }.items():
        monkeypatch.setattr(bootstrap, name, value)
    for key, value in {
        "RANK": "0",
        "LOCAL_RANK": "0",
        "GROUP_RANK": "0",
        "WORLD_SIZE": "1",
        "WANDB_RUN_ID": "job",
    }.items():
        monkeypatch.setenv(key, value)
    response = SimpleNamespace(accepted=True, protocol_version=2, writer_id="writer")
    interface = SimpleNamespace(
        deliver_provenance_start=lambda request: SimpleNamespace(
            wait_or=lambda timeout: response
        ),
        publish_provenance_record=lambda record: None,
    )
    run = SimpleNamespace(
        id="job",
        _settings=SimpleNamespace(x_provenance_level=level),
        _interface=interface,
        _teardown_hooks=[],
    )
    bootstrap.attach_run(run)
    try:
        assert bootstrap.state == bootstrap.BootstrapState.ACTIVE
        assert started.wait(2 if level else 0.2) is (level == 1)
    finally:
        bootstrap.finish_run(run)
