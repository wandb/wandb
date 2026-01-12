from __future__ import annotations

import subprocess

from wandb.util import get_core_path


def test_leet_help_smoke():
    """Smoke test: verify leet binary works and shows help."""
    core_path = get_core_path()

    # Run wandb-core leet --help
    result = subprocess.run(
        [core_path, "leet", "--help"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )

    assert "Lightweight Experiment Exploration Tool" in result.stderr
