import wandb
import tensorflow as tf
from tensorflow.core.framework import summary_pb2


class _WandbHook(tf.train.SessionRunHook):
    def __init__(self, summary_op, steps_per_log=100):
        self._summary_op = summary_op
        self._steps_per_log = steps_per_log

    def begin(self):
        self._step = -1

    def before_run(self, run_context):
        self._step += 1
        return tf.train.SessionRunArgs({"summary": self._summary_op})

    def after_run(self, run_context, run_values):
        if self._step % self._steps_per_log == 0:
            res = run_values.results
            parser = summary_pb2.Summary()
            parser.ParseFromString(res["summary"])
            simple_values = {}
            for value in parser.value:
                kind = value.WhichOneof("value")
                if kind == "simple_value":
                    simple_values[value.tag] = value.simple_value
                elif kind == "image":
                    from PIL import Image
                    import io
                    simple_values["examples"] = simple_values.get(
                        "examples") or []
                    simple_values["examples"].append(wandb.Image(
                        Image.open(io.BytesIO(value.image.encoded_image_string))))
            wandb.log(simple_values)


def test():
    with tf.train.MonitoredTrainingSession(
        checkpoint_dir=".",
        hooks=[tf.train.StopAtStepHook(last_step=2),
               _WandbHook(tf.summary.merge_all(), steps_per_log=100)]) as mon_sess:
        while not mon_sess.should_stop():
            mon_sess.run()


from tensorflow.contrib.learn.python.learn.monitors import EveryN, _extract_output


class WandbSaver(EveryN):
    """Saves tf.summary to WandB
    """

    def __init__(self,
                 save_steps=100):
        """Initializes a `WandbSaver` monitor.
        Args:
          save_steps: `int`, save summaries every N steps. See `EveryN`.
        """
        super(WandbSaver, self).__init__(every_n_steps=save_steps)
        self._summary_op = None

    def begin(self, max_steps=None):
        super(WandbSaver, self).begin(max_steps)
        self._summary_op = tf.summary.merge_all()

    def every_n_step_begin(self, step):
        super(WandbSaver, self).every_n_step_begin(step)
        return [self._summary_op]

    def every_n_step_end(self, step, outputs):
        super(WandbSaver, self).every_n_step_end(step, outputs)
        res = _extract_output(outputs, self._summary_op)
        parser = summary_pb2.Summary()
        parser.ParseFromString(res)
        simple_values = {}
        for value in parser.value:
            kind = value.WhichOneof("value")
            if kind == "simple_value":
                simple_values[value.tag] = value.simple_value
            elif kind == "image":
                from PIL import Image
                import io
                simple_values["examples"] = simple_values.get(
                    "examples") or []
                simple_values["examples"].append(wandb.Image(
                    Image.open(io.BytesIO(value.image.encoded_image_string))))
        wandb.log(simple_values)

        return False


from tensorflow.python.framework import ops
from tensorflow.contrib.learn.python.learn.estimators import test_data


def _run_monitor(monitor,
                 num_epochs=3,
                 num_steps_per_epoch=10,
                 pass_max_steps=True):
    if pass_max_steps:
        max_steps = num_epochs * num_steps_per_epoch - 1
    else:
        max_steps = None
    monitor.begin(max_steps=max_steps)
    for epoch in xrange(num_epochs):
        monitor.epoch_begin(epoch)
        should_stop = False
        step = epoch * num_steps_per_epoch
        next_epoch_step = step + num_steps_per_epoch
        while (not should_stop) and (step < next_epoch_step):
            tensors = monitor.step_begin(step)
            output = ops.get_default_session().run(tensors) if tensors else {}
            output = dict(
                zip([t.name if isinstance(t, ops.Tensor) else t for t in tensors],
                    output))
            should_stop = monitor.step_end(step=step, output=output)
            monitor.post_step(step=step, session=None)
            step += 1
        monitor.epoch_end(epoch)
    monitor.end()


feature_column = tf.contrib.layers.real_valued_column(
    'feature', dimension=4)
# Metrics for linear classifier (no kernels).
est = tf.contrib.learn.LinearClassifier(
    feature_columns=[feature_column], n_classes=3)

with tf.get_default_graph().as_default() as g:
    tf.summary.scalar("loss", 11)
    #_run_monitor(WandbSaver(tf.summary.merge_all()))

    ex = tf.contrib.learn.Experiment(
        est,
        train_input_fn=test_data.iris_input_multiclass_fn,
        eval_input_fn=test_data.iris_input_multiclass_fn,
        train_monitors=[WandbSaver('summary.loss')])
    ex.train_and_evaluate()
