from __future__ import annotations

import ast
import os
import subprocess
import venv
from pathlib import Path

import pytest

from .conftest import CaptureServer

REPO_ROOT = Path(__file__).resolve().parents[4]
_WANDB_INSTALL_SPEC = os.environ.get("WANDB_TEST_WANDB_SPEC", str(REPO_ROOT))


def _protoc_for_pb() -> dict[int, str]:
    """Read the ``_PROTOC_FOR_PB`` map from the repo ``noxfile.py``.

    The noxfile is the single source of truth for which protoc version
    generates each protobuf-major's Python bindings. We parse it with ``ast``
    rather than importing it so this test does not depend on ``nox`` being
    importable in the environment.
    """
    noxfile = REPO_ROOT / "noxfile.py"
    tree = ast.parse(noxfile.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_PROTOC_FOR_PB"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"could not find _PROTOC_FOR_PB in {noxfile}")


# protoc Y.Z corresponds to protobuf X.Y.Z, so the oldest protoc in a major
# series (what the noxfile generates the bindings with) gives the floor runtime
# f"{major}.{protoc}" that the committed wandb/proto/v{major} bindings load
# against -- the most meaningful version to exercise here.
_PROTOBUF_MATRIX = [
    pytest.param(str(major), f"{major}.{protoc}", id=f"protobuf-{major}-floor")
    for major, protoc in sorted(_protoc_for_pb().items())
]

TEST_SCRIPT = """
import os

from wandb.analytics.opentelemetry.opentelemetry_proxy import OtelProvider

endpoint = os.environ["WANDB_TEST_OTEL_ENDPOINT"]
otel = OtelProvider(endpoint=endpoint, pid=os.getpid())
if not otel._boot(export_interval_ms=100):
    raise SystemExit("otel proxy failed to boot")

otel.configure_context({}, {"test": "protobuf_matrix"})
otel.record_metric_and_log_event("wandb.test.protobuf_matrix", {"foo": "bar"})

otel._meter_provider.force_flush()
otel._logger_provider.force_flush()
print("emit-ok")
"""


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


@pytest.mark.parametrize("major, pin", _PROTOBUF_MATRIX)
def test_wandb_install_and_emit_under_pinned_protobuf(
    tmp_path: Path,
    major: str,
    pin: str,
    capture_server: CaptureServer,
) -> None:
    venv_dir = tmp_path / f"venv-pb{major}"
    venv.create(venv_dir, with_pip=True)
    python = _venv_python(venv_dir)

    # Constrain protobuf to the requested version for every install in this env.
    constraints = tmp_path / "constraints.txt"
    constraints.write_text(f"protobuf=={pin}\n")
    _run(python, "-m", "pip", "install", "--upgrade", "pip")
    pre = _run(python, "-m", "pip", "install", f"protobuf=={pin}")
    assert pre.returncode == 0, f"failed to install protobuf=={pin}:\n{pre.stderr}"
    install = _run(
        python,
        "-m",
        "pip",
        "install",
        "-c",
        str(constraints),
        _WANDB_INSTALL_SPEC,
    )

    assert install.returncode == 0, (
        f"installing wandb with protobuf {pin} failed:\n"
        f"{install.stdout}\n{install.stderr}"
    )
    installed = _installed_version(python, "protobuf")
    assert installed == pin, (
        f"protobuf was changed from {pin} to {installed} while installing wandb"
    )

    env = {
        **os.environ,
        "WANDB_TEST_OTEL_ENDPOINT": capture_server.url,
        "WANDB_ERROR_REPORTING": "true",
    }
    emit = subprocess.run(
        [python, "-c", TEST_SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert emit.returncode == 0, (
        f"emitting an OTel event under protobuf {pin} failed:\n"
        f"{emit.stdout}\n{emit.stderr}"
    )
    assert "/sdk/otel/v1/metrics" in capture_server.captured_paths
    assert "/sdk/otel/v1/logs" in capture_server.captured_paths
