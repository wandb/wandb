"""Compatibility guard tests for protobuf vs. OpenTelemetry.

OpenTelemetry's official OTLP exporters serialize through ``opentelemetry-proto``,
which pins ``protobuf`` to ``>=5.0,<7.0``. To avoid imposing that cap on wandb
users (wandb supports protobuf up to ``<8`` via per-major generated proto trees),
``wandb.analytics.opentelemetry_proxy`` uses custom OTLP/JSON exporters
(see ``wandb/analytics/_otlp_exporters.py``) and does not depend on
``opentelemetry-proto`` at all.

This module has two layers:

1. Fast, deterministic guards (run by default) that document the upstream
   ``opentelemetry-proto`` cap ("protobuf ``< 7`` works, ``7.x`` does not") by
   reading its declared ``protobuf`` requirement. They self-skip when
   ``opentelemetry-proto`` is not installed (the normal case for wandb now that
   the custom JSON exporters are used).

2. A slow, opt-in install matrix (``test_wandb_install_and_emit_under_pinned_protobuf``)
   that, for each protobuf major in 5/6/7, builds an isolated virtualenv,
   constrains protobuf to that major, installs wandb, asserts the constrained
   version is preserved, then emits an OTel event end-to-end against a local
   collector. Because wandb no longer depends on ``opentelemetry-proto``, all
   three majors -- including protobuf 7 -- are expected to work. Enable it with
   ``WANDB_TEST_OTEL_PROTOBUF_MATRIX=1``.
"""

from __future__ import annotations

import http.server
import importlib.metadata as importlib_metadata
import os
import subprocess
import threading
import venv
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

OTEL_PROTO_DIST = "opentelemetry-proto"

# Repo root: tests/unit_tests/test_analytics/<this file> -> 3 levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]


# ===========================================================================
# Layer 1: fast, deterministic metadata guards (run by default).
# ===========================================================================

# protobuf releases that MUST remain compatible with OpenTelemetry (< 7).
# OTel's floor is >= 5, so these are drawn from the 5.x and 6.x lines.
SUPPORTED_PROTOBUF_VERSIONS = [
    "5.26.1",
    "5.27.5",
    "5.29.5",
    "6.0.0",
    "6.31.1",
    "6.33.6",
]

# protobuf releases we currently expect OpenTelemetry to REJECT (>= 7).
UNSUPPORTED_PROTOBUF_VERSIONS = [
    "7.0.0",
    "7.34.1",
]


def _otel_proto_protobuf_specifier() -> SpecifierSet:
    """Return the ``protobuf`` version specifier declared by opentelemetry-proto."""
    try:
        requires = importlib_metadata.requires(OTEL_PROTO_DIST)
    except importlib_metadata.PackageNotFoundError:
        pytest.skip(f"{OTEL_PROTO_DIST} is not installed")

    for raw in requires or []:
        requirement = Requirement(raw)
        if requirement.name == "protobuf":
            return requirement.specifier

    pytest.fail(f"{OTEL_PROTO_DIST} does not declare a protobuf dependency")


@pytest.mark.parametrize("version", SUPPORTED_PROTOBUF_VERSIONS)
def test_protobuf_below_v7_is_supported(version: str) -> None:
    """protobuf versions below 7 satisfy opentelemetry-proto's requirement."""
    specifier = _otel_proto_protobuf_specifier()
    assert specifier.contains(version, prereleases=True), (
        f"protobuf {version} should satisfy {OTEL_PROTO_DIST}'s "
        f"requirement {specifier}, but does not"
    )


@pytest.mark.parametrize("version", UNSUPPORTED_PROTOBUF_VERSIONS)
def test_protobuf_v7_is_not_supported(version: str) -> None:
    """protobuf 7.x is rejected by opentelemetry-proto's requirement.

    If this assertion fails, OpenTelemetry has widened its protobuf bound to
    include 7.x -- revisit the OTLP/JSON exporter workaround.
    """
    specifier = _otel_proto_protobuf_specifier()
    assert not specifier.contains(version, prereleases=True), (
        f"protobuf {version} is unexpectedly allowed by {OTEL_PROTO_DIST}'s "
        f"requirement {specifier}; OpenTelemetry may have added protobuf 7 "
        f"support -- revisit the OTLP/JSON exporter workaround"
    )


def test_otel_proto_floor_is_at_least_v5() -> None:
    """Document OTel's lower bound: protobuf < 5 is also unsupported."""
    specifier = _otel_proto_protobuf_specifier()
    assert not specifier.contains("4.25.0", prereleases=True), (
        f"expected {OTEL_PROTO_DIST} to require protobuf >= 5, got {specifier}"
    )


# ===========================================================================
# Layer 2: opt-in install matrix (isolated venv per protobuf major).
#
# Builds wandb from source in a fresh virtualenv, so it is slow and needs
# network access plus the Go/Rust toolchains. Skipped unless
# WANDB_TEST_OTEL_PROTOBUF_MATRIX=1.
# ===========================================================================

_MATRIX_ENABLED = os.environ.get("WANDB_TEST_OTEL_PROTOBUF_MATRIX") == "1"

# Override what gets installed as "wandb" (e.g. a prebuilt wheel) to avoid the
# from-source build cost. Defaults to the repo root.
_WANDB_INSTALL_SPEC = os.environ.get("WANDB_TEST_WANDB_SPEC", str(REPO_ROOT))

# (protobuf major, concrete pin, expected to work). With the custom OTLP/JSON
# exporters, wandb no longer depends on the protobuf-bound opentelemetry-proto,
# so every protobuf major from 5 through 7 must work.
_PROTOBUF_MATRIX = [
    pytest.param("5", "5.29.5", True, id="protobuf-5-ok"),
    pytest.param("6", "6.33.6", True, id="protobuf-6-ok"),
    pytest.param("7", "7.34.1", True, id="protobuf-7-ok"),
]

# Emitted in the child venv: boots the OTel proxy against a local collector,
# records one event, and force-flushes both providers so the export happens
# synchronously before the process exits.
_EMIT_SCRIPT = """
import os
from wandb.analytics import get_otel

endpoint = os.environ["WANDB_TEST_OTEL_ENDPOINT"]
otel = get_otel()
if not otel._boot(endpoint=endpoint, export_interval_ms=100):
    raise SystemExit("otel proxy failed to boot")

otel.configure_scope(high_cardinality_tags={"test": "protobuf_matrix"})
otel.record_metric_and_log_event("wandb.test.protobuf_matrix", {"foo": "bar"})

otel._provider.force_flush()
otel._logger_provider.force_flush()
print("emit-ok")
"""


class _CaptureHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.server.captured_paths.append(self.path)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence the default request logging


class _CaptureServer:
    """A tiny loopback HTTP server that records the paths it receives."""

    def __init__(self) -> None:
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
        self._httpd.captured_paths = []  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> _CaptureServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._thread.join(timeout=5)
        self._httpd.server_close()

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def captured_paths(self) -> list[str]:
        return self._httpd.captured_paths  # type: ignore[attr-defined]


def _venv_python(venv_dir: Path) -> str:
    bindir = "Scripts" if os.name == "nt" else "bin"
    exe = "python.exe" if os.name == "nt" else "python"
    return str(venv_dir / bindir / exe)


def _run(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        env=env,
        timeout=1800,
    )


def _installed_version(python: str, dist: str) -> str:
    result = _run(
        python,
        "-c",
        f"import importlib.metadata as m; print(m.version('{dist}'))",
    )
    assert result.returncode == 0, f"could not read {dist} version:\n{result.stderr}"
    return result.stdout.strip()


@pytest.mark.flaky
@pytest.mark.skipif(
    not _MATRIX_ENABLED,
    reason="set WANDB_TEST_OTEL_PROTOBUF_MATRIX=1 to run the install matrix",
)
@pytest.mark.parametrize("major, pin, should_work", _PROTOBUF_MATRIX)
def test_wandb_install_and_emit_under_pinned_protobuf(
    tmp_path: Path,
    major: str,
    pin: str,
    should_work: bool,
) -> None:
    """Pin protobuf, install wandb, and emit an OTel event.

    For every protobuf major (5, 6, 7) the pinned version must be preserved
    after installing wandb and the emitted event must reach the collector.
    This works because the custom OTLP/JSON exporters drop the dependency on
    opentelemetry-proto (which would otherwise cap protobuf below 7).
    """
    venv_dir = tmp_path / f"venv-pb{major}"
    venv.create(venv_dir, with_pip=True)
    python = _venv_python(venv_dir)

    # Constrain protobuf to the requested version for every install in this env.
    constraints = tmp_path / "constraints.txt"
    constraints.write_text(f"protobuf=={pin}\n")

    _run(python, "-m", "pip", "install", "--upgrade", "pip")

    # Pre-install the pinned protobuf so a later silent change is detectable.
    pre = _run(python, "-m", "pip", "install", f"protobuf=={pin}")
    assert pre.returncode == 0, f"failed to install protobuf=={pin}:\n{pre.stderr}"

    # Install wandb (this branch) under the protobuf constraint. The custom
    # OTLP/JSON exporters mean wandb no longer needs any opentelemetry-proto
    # based exporter, so the install must succeed even at protobuf 7.
    install = _run(
        python,
        "-m",
        "pip",
        "install",
        "-c",
        str(constraints),
        _WANDB_INSTALL_SPEC,
    )

    if not should_work:
        assert install.returncode != 0, (
            f"expected installing wandb with protobuf {pin} to fail because "
            f"opentelemetry-proto caps protobuf < 7, but it succeeded:\n"
            f"{install.stdout}"
        )
        return

    assert install.returncode == 0, (
        f"installing wandb with protobuf {pin} failed:\n"
        f"{install.stdout}\n{install.stderr}"
    )

    # The constrained protobuf version must be preserved, not downgraded.
    installed = _installed_version(python, "protobuf")
    assert installed == pin, (
        f"protobuf was changed from {pin} to {installed} while installing wandb"
    )

    # Emit an event end-to-end and confirm the collector received an export.
    with _CaptureServer() as server:
        env = {**os.environ, "WANDB_TEST_OTEL_ENDPOINT": server.url}
        emit = subprocess.run(
            [python, "-c", _EMIT_SCRIPT],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        assert emit.returncode == 0, (
            f"emitting an OTel event under protobuf {pin} failed:\n"
            f"{emit.stdout}\n{emit.stderr}"
        )
        assert server.captured_paths, (
            f"collector received no OTLP export under protobuf {pin}; "
            f"child output:\n{emit.stdout}"
        )
