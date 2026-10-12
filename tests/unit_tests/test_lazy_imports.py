"""Modules that `import wandb` must leave for later, because loading them is slow."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.fixture(scope="module")
def modules_loaded_by_import_wandb() -> set[str]:
    code = "import sys, wandb; print('\\n'.join(sys.modules))"
    output = subprocess.check_output([sys.executable, "-c", code], text=True)
    return set(output.split())


@pytest.mark.parametrize(
    "module",
    [
        # Generated GraphQL models, hundreds of pydantic classes per package.
        "wandb.sdk.artifacts._generated.fragments",
        "wandb.automations._generated.fragments",
        # The OpenTelemetry SDK is only needed once telemetry is recorded.
        "opentelemetry.sdk.metrics",
        # HTTP sessions are created when something is uploaded or exported.
        "requests",
    ],
)
def test_import_wandb_does_not_load(module, modules_loaded_by_import_wandb):
    assert module not in modules_loaded_by_import_wandb
