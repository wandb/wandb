from __future__ import annotations

from hypothesis import HealthCheck, settings

# default Hypothesis settings
settings.register_profile(
    "default",
    # wandb_core/no_wandb_core tests may end up running on different executors
    suppress_health_check=[HealthCheck.differing_executors],
    max_examples=100,
)
settings.load_profile("default")
