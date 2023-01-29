import tensorflow as tf
import wandb
from tensorboard.compat.proto import summary_pb2


def main():
    wandb.init()

    get_or_create_global_step = getattr(
        tf.train, "get_or_create_global", tf.compat.v1.train.get_or_create_global_step
    )

    MonitoredTrainingSession = getattr(  # noqa: N806
        tf.train,
        "MonitoredTrainingSession",
        tf.compat.v1.train.MonitoredTrainingSession,
    )
    tf_summary = (
        tf.summary if hasattr(tf.summary, "merge_all") else tf.compat.v1.summary
    )

    with tf.Graph().as_default():
        get_or_create_global_step()
        c1 = tf.constant(42)
        tf_summary.scalar("c1", c1)
        summary_op = tf_summary.merge_all()

        with MonitoredTrainingSession(
            hooks=[wandb.tensorflow.WandbHook(summary_op, steps_per_log=1)]
        ) as sess:
            summary, _ = sess.run([summary_op, c1])

    # test digesting encoded summary
    assert wandb.tensorboard.tf_summary_to_dict(summary) == {"c1": 42.0}

    # test digesting Summary object
    summary_pb = summary_pb2.Summary()
    summary_pb.ParseFromString(summary)
    assert wandb.tensorboard.tf_summary_to_dict(summary_pb) == {"c1": 42.0}

    with tf.Graph().as_default():
        get_or_create_global_step()
        c2 = tf.constant(23)
        tf_summary.scalar("c2", c2)
        summary_op = tf_summary.merge_all()

        with MonitoredTrainingSession(
            hooks=[wandb.tensorflow.WandbHook(summary_op, steps_per_log=1)]
        ) as sess:
            summary2, _ = sess.run([summary_op, c2])

    # test digesting a list of encoded summaries
    assert wandb.tensorboard.tf_summary_to_dict([summary, summary2]) == {
        "c1": 42.0,
        "c2": 23.0,
    }


if __name__ == "__main__":
    main()
