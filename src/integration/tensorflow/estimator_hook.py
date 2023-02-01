import tensorflow as tf

import wandb
from wandb.sdk.lib import telemetry

if hasattr(tf.estimator, "SessionRunHook"):
    # In tf 1.14 and beyond, SessionRunHook is in the estimator package.
    SessionRunHook = tf.estimator.SessionRunHook
    SessionRunArgs = tf.estimator.SessionRunArgs
else:
    # In older versions it's in train.
    SessionRunHook = tf.train.SessionRunHook
    SessionRunArgs = tf.train.SessionRunArgs

if hasattr(tf.train, "get_global_step"):
    get_global_step = tf.train.get_global_step
else:
    get_global_step = tf.compat.v1.train.get_global_step

if hasattr(tf.summary, "merge_all"):
    merge_all_summaries = tf.summary.merge_all
else:
    merge_all_summaries = tf.compat.v1.summary.merge_all


class WandbHook(SessionRunHook):
    def __init__(self, summary_op=None, steps_per_log=1000, history=None):
        self._summary_op = summary_op
        self._steps_per_log = steps_per_log
        self._history = history

        with telemetry.context() as tel:
            tel.feature.estimator_hook = True

    def begin(self):
        if wandb.run is None:
            raise wandb.Error("You must call `wandb.init()` before calling `WandbHook`")
        if self._summary_op is None:
            self._summary_op = merge_all_summaries()
        self._step = -1

    def before_run(self, run_context):
        return SessionRunArgs(
            {"summary": self._summary_op, "global_step": get_global_step()}
        )

    def after_run(self, run_context, run_values):
        step = run_values.results["global_step"]
        if step % self._steps_per_log == 0:
            wandb.tensorboard._log(
                run_values.results["summary"],
                history=self._history,
                step=step,
            )
