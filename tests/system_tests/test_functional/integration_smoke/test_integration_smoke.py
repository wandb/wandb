from __future__ import annotations

import importlib
from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class SmokeCase:
    module: str
    attrs: tuple[str, ...]
    imports: tuple[str, ...] = ()


SMOKE_CASES = (
    SmokeCase(
        "wandb.integration.catboost",
        ("WandbCallback", "log_summary"),
        ("catboost",),
    ),
    SmokeCase(
        "wandb.integration.diffusers",
        ("autolog",),
        ("diffusers",),
    ),
    SmokeCase(
        "wandb.integration.dspy",
        ("WandbDSPyCallback",),
        ("dspy",),
    ),
    SmokeCase(
        "wandb.integration.gym",
        ("monitor",),
        ("gymnasium",),
    ),
    SmokeCase(
        "wandb.integration.huggingface",
        ("autolog",),
        ("transformers",),
    ),
    SmokeCase(
        "wandb.integration.keras",
        ("WandbMetricsLogger", "WandbModelCheckpoint", "WandbEvalCallback"),
        ("tensorflow",),
    ),
    SmokeCase(
        "wandb.integration.kfp",
        ("wandb_log", "unpatch_kfp"),
        ("kfp",),
    ),
    SmokeCase(
        "wandb.integration.lightgbm",
        ("wandb_callback", "log_summary"),
        ("lightgbm",),
    ),
    SmokeCase(
        "wandb.integration.lightning.fabric.logger",
        ("WandbLogger",),
        ("lightning", "torch"),
    ),
    SmokeCase(
        "wandb.integration.metaflow",
        ("wandb_log", "wandb_track", "wandb_use"),
        ("metaflow",),
    ),
    SmokeCase(
        "wandb.integration.openai.fine_tuning",
        ("WandbLogger",),
        ("openai", "pandas"),
    ),
    SmokeCase(
        "wandb.integration.sagemaker",
        ("sagemaker_auth", "parse_sm_config", "parse_sm_secrets"),
    ),
    SmokeCase(
        "wandb.integration.sb3",
        ("WandbCallback",),
        ("stable_baselines3",),
    ),
    SmokeCase(
        "wandb.integration.sklearn",
        ("plot_classifier", "plot_regressor", "plot_clusterer"),
        ("sklearn", "pandas"),
    ),
    SmokeCase(
        "wandb.integration.tensorboard",
        ("log", "patch", "unpatch"),
        ("tensorboard",),
    ),
    SmokeCase(
        "wandb.integration.tensorflow",
        ("WandbHook", "log"),
        ("tensorflow",),
    ),
    SmokeCase(
        "wandb.integration.torch.wandb_torch",
        ("TorchGraph",),
    ),
    SmokeCase(
        "wandb.integration.weave",
        ("active_run_path", "RunPath", "setup"),
    ),
    SmokeCase(
        "wandb.integration.xgboost",
        ("WandbCallback", "wandb_callback"),
        ("xgboost",),
    ),
)


@pytest.mark.parametrize("case", SMOKE_CASES, ids=lambda case: case.module)
def test_integration_import_smoke(case: SmokeCase) -> None:
    for import_name in case.imports:
        pytest.importorskip(import_name)

    module = importlib.import_module(case.module)

    for attr in case.attrs:
        assert hasattr(module, attr)
