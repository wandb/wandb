"""
catboost init
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Union

from catboost import CatBoostClassifier, CatBoostRegressor
import wandb


class WandbCallback:
    """`WandbCallback` automatically integrates CatBoost with wandb.

    Arguments:
        - metric_period: (int) if you are passing `metric_period` to your CatBoost model please pass the same value here (default=1).

    Passing `WandbCallback` to CatBoost will:
    - log training and validation metrics at every `metric_period`
    - log iteration at every `metric_period`

    Example:
        ```
        train_pool = Pool(train[features], label=train['label'], cat_features=cat_features)
        test_pool = Pool(test[features], label=test['label'], cat_features=cat_features)

        model = CatBoostRegressor(
            iterations=100,
            loss_function='Cox',
            eval_metric='Cox',
        )

        model.fit(train_pool,
                  eval_set=test_pool,
                  callbacks=[WandbCallback()])
        ```
    """

    def __init__(self, metric_period: int = 1):
        if wandb.run is None:
            raise wandb.Error("You must call wandb.init() before WandbCallback()")

        self.metric_period = metric_period

    def after_iteration(self, info: SimpleNamespace):
        if info.iteration % self.metric_period == 0:
            for data, metric in info.metrics.items():
                for metric_name, log in metric.items():
                    wandb.log({f"{data}-{metric_name}": log[-1]}, commit=False)

            wandb.log({f"iteration@metric-period-{self.metric_period}": info.iteration})

        return True


def _checkpoint_artifact(
    model: Union[CatBoostClassifier, CatBoostRegressor], aliases: list
):
    """
    Upload model checkpoint as W&B artifact
    """
    model_name = f"model_{wandb.run.id}"
    # save the model in the default `cbm` format
    model_path = Path(wandb.run.dir) / "model"

    model.save_model(model_path)

    model_artifact = wandb.Artifact(name=model_name, type="model")
    model_artifact.add_file(model_path)
    wandb.log_artifact(model_artifact, aliases=aliases)


def _log_feature_importance(model):
    """
    Log feature importance with default settings.
    """
    feat_df = model.get_feature_importance(prettified=True)

    fi_data = [
        [feat, feat_imp]
        for feat, feat_imp in zip(feat_df["Feature Id"], feat_df["Importances"])
    ]
    table = wandb.Table(data=fi_data, columns=["Feature", "Importance"])
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
):
    """`log_summary` logs useful metrics about catboost model after training is done

    Arguments:
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
        train_pool = Pool(train[features], label=train['label'], cat_features=cat_features)
        test_pool = Pool(test[features], label=test['label'], cat_features=cat_features)

        model = CatBoostRegressor(
            iterations=100,
            loss_function='Cox',
            eval_metric='Cox',
        )

        model.fit(train_pool,
                  eval_set=test_pool,
                  callbacks=[WandbCallback()])

        log_summary(model)
        ```
    """
    if wandb.run is None:
        raise wandb.Error("You must call wandb.init() before WandbCallback()")

    if not (
        isinstance(model, CatBoostClassifier) or isinstance(model, CatBoostRegressor)
    ):
        raise wandb.Error(
            "Model should be an instance of CatBoostClassifier or CatBoostRegressor"
        )

    # log configs
    params = model.get_all_params()
    if log_all_params:
        wandb.config.update(params)

    # log best score and iteration
    wandb.run.summary["best_iteration"] = model.get_best_iteration()
    wandb.run.summary["best_score"] = model.get_best_score()

    # log model
    if save_model_checkpoint:
        if params["use_best_model"]:
            _checkpoint_artifact(model, aliases=["best"])
        else:
            _checkpoint_artifact(model, aliases=["last"])

    # Feature importance
    if log_feature_importance:
        _log_feature_importance(model)
