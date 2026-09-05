"""Tests for wandb gym/gymnasium integration (e.g. monitor, RecordVideo upload).

To run the gymnasium test (so it does not skip), install gymnasium (and moviepy for
older gymnasium), e.g.:
  pip install -r requirements/requirements_dev.txt
or: uv pip install gymnasium 'moviepy~=1.0'
Then: pytest tests/unit_tests/test_gym_integration.py -v
"""

import pytest


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("gymnasium") is None,
    reason="gymnasium not installed",
)
def test_gymnasium_ge_1_0_patches_video_upload():
    """With Gymnasium >= 1.0, monitor() patches so RecordVideo videos upload to W&B (#11193)."""
    import gymnasium as gym
    import wandb
    from packaging.version import parse
    from wandb.integration import gym as gym_integration

    if parse(gym.__version__) < parse("1.0.0a1"):
        pytest.skip("test only applies to Gymnasium >= 1.0")

    if not wandb.patched.get("gym"):
        gym_integration.monitor()

    entries = wandb.patched["gym"]
    assert entries, "gym.monitor() should append a patch entry"
    patch_target = entries[-1][0]
    if "gymnasium" in patch_target:
        # Either old path (monitoring.video_recorder.VideoRecorder) or new (rendering.RecordVideo)
        assert (
            "monitoring.video_recorder.VideoRecorder" in patch_target
            or "rendering.RecordVideo" in patch_target
        ), (
            f"Gymnasium >= 1.0 must patch VideoRecorder or RecordVideo so videos upload; got {patch_target!r}"
        )
