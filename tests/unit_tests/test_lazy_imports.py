"""Modules that `import wandb` must leave for later, because loading them is slow."""

from __future__ import annotations

import subprocess
import sys

import pytest


def _modules_loaded_by(statement: str) -> set[str]:
    code = f"import sys; {statement}; print('\\n'.join(sys.modules))"
    output = subprocess.check_output([sys.executable, "-c", code], text=True)
    return set(output.split())


@pytest.fixture(scope="module")
def modules_loaded_by_import_wandb() -> set[str]:
    return _modules_loaded_by("import wandb")


@pytest.fixture(scope="module")
def modules_loaded_by_cli() -> set[str]:
    return _modules_loaded_by("import wandb.cli.cli")


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
        # The public API and launch serve `wandb.Api()` and the CLI.
        "wandb.apis.public",
        "wandb.sdk.launch",
    ],
)
def test_import_wandb_does_not_load(module, modules_loaded_by_import_wandb):
    assert module not in modules_loaded_by_import_wandb


@pytest.mark.parametrize(
    "module",
    [
        # Only `wandb verify` makes HTTP requests of its own.
        "requests",
        "wandb.sdk.verify.verify",
        # Only `wandb launch-sweep` reads YAML.
        "yaml",
        "wandb.apis.public",
    ],
)
def test_cli_does_not_load(module, modules_loaded_by_cli):
    assert module not in modules_loaded_by_cli
