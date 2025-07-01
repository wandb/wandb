"""catboost init."""

from pathlib import Path
from types import SimpleNamespace
from typing import List, Union

from catboost import CatBoostClassifier, CatBoostRegressor  # type: ignore

import wandb
from wandb.sdk.lib import telemetry as wb_telemetry


class WandbCallback:
    """`WandbCallback` automatically integrates CatBoost with wandb.

    Args:
        - metric_period: (int) if you are passing `metric_period` to your CatBoost model please pass the same value here (default=1).

    Passing `WandbCallback` to CatBoost will:
    - log training and validation metrics at every `metric_period`
    - log iteration at every `metric_period`

    Example:
        ```
        train_pool = Pool(
            train[features], label=train["label"], cat_features=cat_features
        )
        test_pool = Pool(test[features], label=test["label"], cat_features=cat_features)

        model = CatBoostRegressor(
            iterations=100,
            loss_function="Cox",
            eval_metric="Cox",
        )

        model.fit(
            train_pool,
            eval_set=test_pool,
            callbacks=[WandbCallback()],
        )
        ```
    """

    def __init__(self, metric_period: int = 1):
        if wandb.run is None:
            raise wandb.Error("You must call `wandb.init()` before `WandbCallback()`")

        with wb_telemetry.context() as tel:
            tel.feature.catboost_wandb_callback = True

        self.metric_period: int = metric_period

    def after_iteration(self, info: SimpleNamespace) -> bool:
        if info.iteration % self.metric_period == 0:
            for data, metric in info.metrics.items():
                for metric_name, log in metric.items():
                    # todo: replace with wandb.run._log once available
                    wandb.log({f"{data}-{metric_name}": log[-1]}, commit=False)
            # todo: replace with wandb.run._log once available
            wandb.log({f"iteration@metric-period-{self.metric_period}": info.iteration})

        return True


def _checkpoint_artifact(
    model: Union[CatBoostClassifier, CatBoostRegressor], aliases: List[str]
) -> None:
    """Upload model checkpoint as W&B artifact."""
    if wandb.run is None:
        raise wandb.Error(
            "You must call `wandb.init()` before `_checkpoint_artifact()`"
        )

    model_name = f"model_{wandb.run.id}"
    # save the model in the default `cbm` format
    model_path = Path(wandb.run.dir) / "model"

    model.save_model(model_path)

    model_artifact = wandb.Artifact(name=model_name, type="model")
    model_artifact.add_file(str(model_path))
    wandb.log_artifact(model_artifact, aliases=aliases)


def _log_feature_importance(
    model: Union[CatBoostClassifier, CatBoostRegressor],
) -> None:
    """Log feature importance with default settings."""
    if wandb.run is None:
        raise wandb.Error(
            "You must call `wandb.init()` before `_checkpoint_artifact()`"
        )

    feat_df = model.get_feature_importance(prettified=True)

    fi_data = [
        [feat, feat_imp]
        for feat, feat_imp in zip(feat_df["Feature Id"], feat_df["Importances"])
    ]
    table = wandb.Table(data=fi_data, columns=["Feature", "Importance"])
    # todo: replace with wandb.run._log once available
    wandb.log(
        {
            "Feature Importance": wandb.plot.bar(
                table, "Feature", "Importance", title="Feature Importance"
            )
        },
        commit=False,
    )


def log_summary(
    model: Union[CatBoostClassifier, CatBoostRegressor],
    log_all_params: bool = True,
    save_model_checkpoint: bool = False,
    log_feature_importance: bool = True,
) -> None:
    """`log_summary` logs useful metrics about catboost model after training is done.

    Args:
        model: it can be CatBoostClassifier or CatBoostRegressor.
        log_all_params: (boolean) if True (default) log the model hyperparameters as W&B config.
        save_model_checkpoint: (boolean) if True saves the model upload as W&B artifacts.
        log_feature_importance: (boolean) if True (default) logs feature importance as W&B bar chart using the default setting of `get_feature_importance`.

    Using this along with `wandb_callback` will:

    - save the hyperparameters as W&B config,
    - log `best_iteration` and `best_score` as `wandb.summary`,
    - save and upload your trained model to Weights & Biases Artifacts (when `save_model_checkpoint = True`)
    - log feature importance plot.

    Example:
        ```python
        train_pool = Pool(
            train[features], label=train["label"], cat_features=cat_features
        )
        test_pool = Pool(test[features], label=test["label"], cat_features=cat_features)

        model = CatBoostRegressor(
            iterations=100,
            loss_function="Cox",
            eval_metric="Cox",
        )

        model.fit(
            train_pool,
            eval_set=test_pool,
            callbacks=[WandbCallback()],
        )

        log_summary(model)
        ```
    """
    if wandb.run is None:
        raise wandb.Error("You must call `wandb.init()` before `log_summary()`")

    if not (isinstance(model, (CatBoostClassifier, CatBoostRegressor))):
        raise wandb.Error(
            "Model should be an instance of CatBoostClassifier or CatBoostRegressor"
        )

    with wb_telemetry.context() as tel:
        tel.feature.catboost_log_summary = True

    # log configs
    params = model.get_all_params()
    if log_all_params:
        wandb.config.update(params)

    # log best score and iteration
    wandb.run.summary["best_iteration"] = model.get_best_iteration()
    wandb.run.summary["best_score"] = model.get_best_score()

    # log model
    if save_model_checkpoint:
        aliases = ["best"] if params["use_best_model"] else ["last"]
        _checkpoint_artifact(model, aliases=aliases)

    # Feature importance
    if log_feature_importance:
        _log_feature_importance(model)
