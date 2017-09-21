
# New tensorflow file writer that also updates wandb
#
# Usage:
# history = wandb.History()
# summary = wandb.Summary()
#
# summary_writer = WandbFileWriter(FLAGS.log_dir, wandb_summary=summary, wandb_history=history)
#
#     slim.learning.train(
#        train_op,
#        FLAGS.log_dir,
#        summary_writer=summary_writer)
#

from tensorflow.python.summary import summary
from tensorflow.python.summary.writer.event_file_writer import EventFileWriter
import wandb


class WandbEventFileWriter(EventFileWriter):
    def __init__(self, logdir, max_queue=10, flush_secs=120,
                 filename_suffix=None, wandb_summary=None, wandb_history=None):
        self._wandb_summary = wandb_summary
        self._wandb_history = wandb_history
        super(WandbEventFileWriter, self).__init__(logdir, max_queue, flush_secs,
                                                   filename_suffix)

    def add_event(self, event):
        for v in event.summary.value:
            if v.simple_value:
                print("Tag: " + v.tag + " Val: " + str(v.simple_value))
                self._wandb_summary[v.tag] = v.simple_value

        super(WandbEventFileWriter, self).add_event(event)


class WandbFileWriter(summary.FileWriter):
    def __init__(self,
                 logdir,
                 graph=None,
                 max_queue=10,
                 flush_secs=120,
                 graph_def=None,
                 filename_suffix=None,
                 wandb_summary=None,
                 wandb_history=None):

        event_writer = WandbEventFileWriter(logdir, max_queue, flush_secs,
                                            filename_suffix, wandb_summary, wandb_history)

        super(summary.FileWriter, self).__init__(
            event_writer, graph, graph_def)
