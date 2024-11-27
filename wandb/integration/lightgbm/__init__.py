"""W&B callback for lightgbm.

Really simple callback to get logging for each tree

Example usage:

param_list = [("eta", 0.08), ("max_depth", 6), ("subsample", 0.8), ("colsample_bytree", 0.8), ("alpha", 8), ("num_class", 10)]
config.update(dict(param_list))
lgb = lgb.train(param_list, d_train, callbacks=[wandb_callback()])
"""

from pathlib import Path
from typing import TYPE_CHECKING, Callable

import lightgbm  # type: ignore
from lightgbm import Booster

import wandb
from wandb.sdk.lib import telemetry as wb_telemetry

MINIMIZE_METRICS = [
    "l1",
    "l2",
    "rmse",
    "mape",
    "huber",
    "fair",
    "poisson",
    "gamma",
    "binary_logloss",
]

MAXIMIZE_METRICS = ["map", "auc", "average_precision"]


if TYPE_CHECKING:
    from typing import Any, Dict, List, NamedTuple, Tuple, Union

    # Note: upstream lightgbm has this defined incorrectly
    _EvalResultTuple = Union[
        Tuple[str, str, float, bool], Tuple[str, str, float, bool, float]
    ]

    class CallbackEnv(NamedTuple):
        model: Any
        params: Dict
        iteration: int
        begin_interation: int
        end_iteration: int
        evaluation_result_list: List[_EvalResultTuple]


def _define_metric(data: str, metric_name: str) -> None:
    """Capture model performance at the best step.

    instead of the last step, of training in your `wandb.summary`
    """
    if "loss" in str.lower(metric_name):
        wandb.define_metric(f"{data}_{metric_name}", summary="min")
    elif str.lower(metric_name) in MINIMIZE_METRICS:
        wandb.define_metric(f"{data}_{metric_name}", summary="min")
    elif str.lower(metric_name) in MAXIMIZE_METRICS:
        wandb.define_metric(f"{data}_{metric_name}", summary="max")


def _checkpoint_artifact(
    model: "Booster", iteration: int, aliases: "List[str]"
) -> None:
    """Upload model checkpoint as W&B artifact."""
    # NOTE: type ignore required because wandb.run is improperly inferred as None type
    model_name = f"model_{wandb.run.id}"  # type: ignore
    model_path = Path(wandb.run.dir) / f"model_ckpt_{iteration}.txt"  # type: ignore

    model.save_model(model_path, num_iteration=iteration)

    model_artifact = wandb.Artifact(name=model_name, type="model")
    model_artifact.add_file(str(model_path))
    wandb.log_artifact(model_artifact, aliases=aliases)


def _log_feature_importance(model: "Booster") -> None:
    """Log feature importance."""
    feat_imps = model.feature_importance()
    feats = model.feature_name()
    fi_data = [[feat, feat_imp] for feat, feat_imp in zip(feats, feat_imps)]
    table = wandb.Table(data=fi_data, columns=["Feature", "Importance"])
    wandb.log(
        {
            "Feature Importance": wandb.plot.bar(
                table, "Feature", "Importance", title="Feature Importance"
            )
        },
        commit=False,
    )


class _WandbCallback:
    """Internal class to handle `wandb_callback` logic.

    This callback is adapted form the LightGBM's `_RecordEvaluationCallback`.
    """

    def __init__(self, log_params: bool = True, define_metric: bool = True) -> None:
        self.order = 20
        self.before_iteration = False
        self.log_params = log_params
        self.define_metric_bool = define_metric

    def _init(self, env: "CallbackEnv") -> None:
        with wb_telemetry.context() as tel:
            tel.feature.lightgbm_wandb_callback = True

        # log the params as W&B config.
        if self.log_params:
            wandb.config.update(env.params)

        # use `define_metric` to set the wandb summary to the best metric value.
        for item in env.evaluation_result_list:
            if self.define_metric_bool:
                if len(item) == 4:
                    data_name, eval_name = item[:2]
                    _define_metric(data_name, eval_name)
                else:
                    data_name, eval_name = item[1].split()
                    _define_metric(data_name, f"{eval_name}-mean")
                    _define_metric(data_name, f"{eval_name}-stdv")

    def __call__(self, env: "CallbackEnv") -> None:
        if env.iteration == env.begin_iteration:  # type: ignore
            self._init(env)

        for item in env.evaluation_result_list:
            if len(item) == 4:
                data_name, eval_name, result = item[:3]
                wandb.log(
                    {data_name + "_" + eval_name: result},
                    commit=False,
                )
            else:
                data_name, eval_name = item[1].split()
                res_mean = item[2]
                res_stdv = item[4]
                wandb.log(
                    {
                        data_name + "_" + eval_name + "-mean": res_mean,
                        data_name + "_" + eval_name + "-stdv": res_stdv,
                    },
                    commit=False,
                )

        # call `commit=True` to log the data as a single W&B step.
        wandb.log({"iteration": env.iteration}, commit=True)


def wandb_callback(log_params: bool = True, define_metric: bool = True) -> Callable:
    """Automatically integrates LightGBM with wandb.

    Args:
        log_params: (boolean) if True (default) logs params passed to lightgbm.train as W&B config
        define_metric: (boolean) if True (default) capture model performance at the best step, instead of the last step, of training in your `wandb.summary`

    Passing `wandb_callback` to LightGBM will:
      - log params passed to lightgbm.train as W&B config (default).
      - log evaluation metrics collected by LightGBM, such as rmse, accuracy etc to Weights & Biases
      - Capture the best metric in `wandb.summary` when `define_metric=True` (default).

    Use `log_summary` as an extension of this callback.

    Example:
        ```python
        params = {
            "boosting_type": "gbdt",
            "objective": "regression",
        }
        gbm = lgb.train(
            params,
            lgb_train,
            num_boost_round=10,
            valid_sets=lgb_eval,
            valid_names=("validation"),
            callbacks=[wandb_callback()],
        )
        ```
    """
    return _WandbCallback(log_params, define_metric)


def log_summary(
    model: Booster, feature_importance: bool = True, save_model_checkpoint: bool = False
) -> None:
    """Log useful metrics about lightgbm model after training is done.

    Args:
        model: (Booster) is an instance of lightgbm.basic.Booster.
        feature_importance: (boolean) if True (default), logs the feature importance plot.
        save_model_checkpoint: (boolean) if True saves the best model and upload as W&B artifacts.

    Using this along with `wandb_callback` will:

    - log `best_iteration` and `best_score` as `wandb.summary`.
    - log feature importance plot.
    - save and upload your best trained model to Weights & Biases Artifacts (when `save_model_checkpoint = True`)

    Example:
        ```python
        params = {
            "boosting_type": "gbdt",
            "objective": "regression",
        }
        gbm = lgb.train(
            params,
            lgb_train,
            num_boost_round=10,
            valid_sets=lgb_eval,
            valid_names=("validation"),
            callbacks=[wandb_callback()],
        )

        log_summary(gbm)
        ```
    """
    if wandb.run is None:
        raise wandb.Error("You must call wandb.init() before WandbCallback()")

    if not isinstance(model, Booster):
        raise wandb.Error("Model should be an instance of lightgbm.basic.Booster")

    wandb.run.summary["best_iteration"] = model.best_iteration
    wandb.run.summary["best_score"] = model.best_score

    # Log feature importance
    if feature_importance:
        _log_feature_importance(model)

    if save_model_checkpoint:
        _checkpoint_artifact(model, model.best_iteration, aliases=["best"])

    with wb_telemetry.context() as tel:
        tel.feature.lightgbm_log_summary = True
