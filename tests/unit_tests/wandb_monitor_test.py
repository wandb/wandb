import random
import sys

import numpy as np
import pytest
import wandb


pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 5),
    reason="@wandb.beta.monitor requires Python 3.x",
)


def to_table(calls):
    table = wandb.Table(["Input", "Output"])
    for call in calls:
        best_idx = np.argmax(call.results[0])
        table.add_data(wandb.Image(call.args[0]), call.results[0][best_idx])
    return table


def test_monitor_function_auto_init(test_settings, live_mock_server):
    @wandb.beta.monitor(settings=test_settings, to_table=to_table)
    def predict(stuff):
        return [random.random(), random.random()]

    predict(np.random.randint(0, 255, (10, 10)))
    predict.wandb_monitor.flush()
    wandb.finish()
    ctx = live_mock_server.get_ctx()
    print(ctx)
    assert ctx["artifacts"] is not None
    assert ctx["summary"]["calls"] == 1
    assert ctx["summary"]["input_0"]["_type"] == "histogram"


def test_monitor_class_manual_init(test_settings, live_mock_server):
    with wandb.init(settings=test_settings):

        @wandb.beta.monitor(settings=test_settings)
        class Foo:
            def predict(self, stuff):
                return [random.random(), random.random()]

            def to_table(self, calls):
                return to_table(calls)

        foo = Foo()
        foo.predict(np.random.randint(0, 255, (10, 10)))
        foo.wandb_monitor.flush()
    ctx = live_mock_server.get_ctx()
    print(ctx)
    assert ctx["artifacts"] is not None
    assert ctx["summary"]["calls"] == 1
    assert ctx["summary"]["input_0"]["_type"] == "histogram"


def test_monitor_function_on_class(test_settings, live_mock_server):
    class Foo:
        @wandb.beta.monitor(settings=test_settings)
        def predict(self, stuff):
            return [random.random(), random.random()]

        def to_table(self, calls):
            return to_table(calls)

    foo = Foo()
    foo.predict(np.random.randint(0, 255, (10, 10)))
    foo.predict.wandb_monitor.flush()
    wandb.finish()
    ctx = live_mock_server.get_ctx()
    print(ctx)
    assert ctx["artifacts"] is not None
    assert ctx["summary"]["calls"] == 1
    assert ctx["summary"]["input_0"]["_type"] == "histogram"


def test_monitor_manual(test_settings, live_mock_server):
    wandb_monitor = wandb.beta.Monitor(settings=test_settings, to_table=to_table)
    wandb_monitor.input(np.random.randint(0, 255, (10, 10)))
    wandb_monitor.output([random.random(), random.random()])
    wandb_monitor.flush()
    wandb.finish()
    ctx = live_mock_server.get_ctx()
    print(ctx)
    assert ctx["artifacts"] is not None
    assert ctx["summary"]["calls"] == 1
    assert ctx["summary"]["input_0"]["_type"] == "histogram"
