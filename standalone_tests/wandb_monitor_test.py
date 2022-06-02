import time

import wandb
import numpy as np

labels = ["foo", "bar", "baz"]


@wandb.beta.monitor(flush_interval=10, settings={"project": "test_monitor"})
class Model:
    def predict(self, input, id=None):
        return np.random.random((3,))

    def to_table(self, calls):
        table = wandb.Table(["Input", "Output", "Label", "ID"])
        rows = 0
        for call in calls:
            rows += 1
            best_idx = np.argmax(call.results[0])
            table.add_data(
                wandb.Image(call.args[0]),
                call.results[0][best_idx],
                labels[best_idx],
                call.kwargs["id"],
            )
        print(f"Flushed {rows} rows")
        return table


model = Model()
for i in range(100):
    res = model.predict(np.random.random((28, 28, 1)), id=i)
    if i % 10 == 0:
        if i != 0:
            print(f"Predicted {i} images, most recent {res}")
        if i == 20:
            print("Disabled monitoring")
            model.wandb_monitor.disable()
        if i == 30:
            print("Enabled monitoring")
            model.wandb_monitor.enable()
        time.sleep(5)
    if i == 40:
        print("Manual flush")
        model.wandb_monitor.flush()
