"""W&B callback for lightgbm.

Really simple callback to get logging for each tree

Example usage:

param_list = [("eta", 0.08), ("max_depth", 6), ("subsample", 0.8), ("colsample_bytree", 0.8), ("alpha", 8), ("num_class", 10)]
config.update(dict(param_list))
lgb = lgb.train(param_list, d_train, callbacks=[wandb_callback()])
"""

from pathlib import Path
from typing import Callable
from typing import TYPE_CHECKING

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
    model_artifact.add_file(model_path)
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


def wandb_callback(log_params: bool = True, define_metric: bool = True) -> Callable:
    """Automatically integrates LightGBM with wandb.

    Arguments:
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
            'boosting_type': 'gbdt',
            'objective': 'regression',
            .
        }
        gbm = lgb.train(params,
                        lgb_train,
                        num_boost_round=10,
                        valid_sets=lgb_eval,
                        valid_names=('validation'),
                        callbacks=[wandb_callback()])
        ```
    """
    log_params_list: "List[bool]" = [log_params]
    define_metric_list: "List[bool]" = [define_metric]

    def _init(env: "CallbackEnv") -> None:
        with wb_telemetry.context() as tel:
            tel.feature.lightgbm_wandb_callback = True

        wandb.config.update(env.params)
        log_params_list[0] = False

        if define_metric_list[0]:
            for i in range(len(env.evaluation_result_list)):
                data_type = env.evaluation_result_list[i][0]
                metric_name = env.evaluation_result_list[i][1]
                _define_metric(data_type, metric_name)

    def _callback(env: "CallbackEnv") -> None:
        if log_params_list[0]:
            _init(env)

        eval_results: "Dict[str, Dict[str, List[Any]]]" = {}
        recorder = lightgbm.record_evaluation(eval_results)
        recorder(env)

        for validation_key in eval_results.keys():
            for key in eval_results[validation_key].keys():
                wandb.log(
                    {validation_key + "_" + key: eval_results[validation_key][key][0]},
                    commit=False,
                )

        # Previous log statements use commit=False. This commits them.
        wandb.log({"iteration": env.iteration}, commit=True)

    return _callback


def log_summary(
    model: Booster, feature_importance: bool = True, save_model_checkpoint: bool = False
) -> None:
    """Logs useful metrics about lightgbm model after training is done.

    Arguments:
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
            'boosting_type': 'gbdt',
            'objective': 'regression',
            .
        }
        gbm = lgb.train(params,
                        lgb_train,
                        num_boost_round=10,
                        valid_sets=lgb_eval,
                        valid_names=('validation'),
                        callbacks=[wandb_callback()])

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
