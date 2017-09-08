from wandb import history
from wandb import summary

# Fully implemented here so we don't have to pull in keras as a dependency.
# However, if the user is using this, they necessarily have Keras installed. So we
# could probably selectively build this class only when the user requests it,
# knowing that keras is available.
class WandBKerasCallback(object):
    """WandB Keras Callback.

    Automatically saves wandb-history.csv and wandb-summary.csv, both tracking
    keras metrics.
    """

    default_summary_strategy = {
        'loss': 'min',
        'val_loss': 'min',
        'acc': 'max',
        'val_acc': 'max'
    }

    def __init__(self, out_dir='.', summary_strategy={}):
        """Constructor.
    
        Args:
            out_dir: Directory to save history/summary files in.
            summary_strategy: A dict of <metric_name>:<'min'|'max'|'latest'>
                pairs. Defaults to 'latest' for metric names that aren't
                provided. If strategy is 'min' for we keep the minimum
                value seen for that key. If 'max' we keep maximum, if
                'latest' we keep the most recent.
        """
        self.validation_data = None
        self.out_dir = out_dir
        self.summary_strategy = summary_strategy
        self.history = None
        self.summary = None

    def set_params(self, params):
        self.params = params

    def set_model(self, model):
        self.model = model

    def on_epoch_begin(self, epoch, logs=None):
        pass

    def on_epoch_end(self, epoch, logs=None):
        # history
        if self.history is None:
            self.history = history.History(
                    ['epoch'] + sorted(logs.keys()),
                    out_dir=self.out_dir)
        row = {'epoch': epoch}
        row.update(logs)
        self.history.add(row)

        # summary
        summary = {}
        for k, v in row.items():
            strategy = (
                    self.summary_strategy.get(k)
                    or self.default_summary_strategy.get(k, 'latest'))
            cur_val = self.summary.get(k)
            if cur_val is None or strategy == 'latest':
                summary[k] = v
            elif strategy == 'min' and v < cur_val:
                summary[k] = v
            elif strategy == 'max' and v > cur_val:
                summary[k] = v
        self.summary.update(summary)

    def on_batch_begin(self, batch, logs=None):
        pass

    def on_batch_end(self, batch, logs=None):
        pass

    def on_train_begin(self, logs=None):
        self.summary = summary.Summary(self.out_dir)

    def on_train_end(self, logs=None):
        if self.history is not None:
            self.history.close()