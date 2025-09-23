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
    )

    print(result.stderr)

    # Should exit with 0
    assert result.returncode == 0, f"leet --help exited with {result.returncode}"
