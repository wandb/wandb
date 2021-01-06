import wandb
import time
import numpy as np

wandb.init(project="test_monitor")
labels = ["foo", "bar", "baz"]


def to_table(calls):
    table = wandb.Table(["Input", "Output", "Label", "ID"])
    rows = 0
    for call in calls:
        rows += 1
        best_idx = np.argmax(call.results[0])
        table.add_data(wandb.Image(call.args[0]), call.results[0][best_idx], labels[best_idx], call.kwargs["id"])
    print("Flushed {} rows".format(rows))
    return table


@wandb.monitor(to_table=to_table, flush_interval=10)
def predict(input, id=None):
    return np.random.random((3,))


for i in range(100):
    res = predict(np.random.random((28,28,1)), id=i)
    if i % 10 == 0:
        if i != 0:
            print("Predicted {} images, most recent {}".format(i, res))
        if i == 20:
            print("Disabled monitoring")
            predict.disable()
        if i == 30:
            print("Enabled monitoring")
            predict.enable()
        time.sleep(5)
    if i == 40:
        print("Manual flush")
        predict.flush()
