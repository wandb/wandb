from wandb.sdk import internal
import time
import os
import wandb
import pytest
import sys
import torch
import torch.nn.functional as F
from wandb.sdk.internal import profiler

from wandb.sdk.internal.profiler import ProfilerWatcher


@pytest.mark.skipif(
    sys.version_info >= (3, 9), reason="PyTorch not currently stable for 3.9"
)
def test_profiler_watcher(
    runner, mock_server, test_settings, backend_interface, internal_hm
):
    """
    This test simulates a typical use-case for PyTorch Profiler: training performance.
    It generates random noise and trains a simple conv net on this noise
    using the torch profiler api.

    Doing so dumps a "pt.trace.json" file in the given logdir.

    This unittest then ensures that ProfilerWatcher syncs this file to the backend.
    """

    def random_batch_generator():
        for i in range(10):
            # create 1-sized batches of 28x28 random noise (simulating images)
            yield i, (torch.randn((1, 1, 28, 28)), torch.randint(0, 10, (1,)))

    class Net(torch.nn.Module):
        def __init__(self):
            super(Net, self).__init__()
            self.conv1 = torch.nn.Conv2d(1, 32, 3, 1)
            self.conv2 = torch.nn.Conv2d(32, 64, 3, 1)
            self.fc1 = torch.nn.Linear(9216, 128)
            self.fc2 = torch.nn.Linear(128, 10)

        def forward(self, x):
            x = F.relu(self.conv1(x))
            x = F.relu(self.conv2(x))
            x = F.max_pool2d(x, 2)
            x = torch.flatten(x, 1)
            x = F.relu(self.fc1(x))
            x = self.fc2(x)
            output = F.log_softmax(x, dim=1)
            return output

    model = Net()
    criterion = torch.nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.001, momentum=0.9)
    model.train()

    def train(data):
        inputs, labels = data[0], data[1]
        outputs = model(inputs)
        loss = criterion(outputs, labels)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

    with runner.isolated_filesystem():
        logdir = "./boom"
        wandb.util.mkdir_exists_ok("boom")
        # wandb.init(settings=test_settings)

        # Watch `logdir` for `*trace.json` files
        with backend_interface() as interface:
            prof_watcher = ProfilerWatcher(interface=interface, settings=test_settings)
            prof_watcher._polling_interval = 0.1
            prof_watcher.add(logdir)
            prof_watcher.start()

            with torch.profiler.profile(
                schedule=torch.profiler.schedule(wait=1, warmup=1, active=3, repeat=1),
                on_trace_ready=torch.profiler.tensorboard_trace_handler(logdir),
                record_shapes=True,
                with_stack=True,
            ) as prof:
                for step, batch_data in random_batch_generator():
                    if step >= (1 + 1 + 3) * 1:
                        break
                    train(batch_data)
                    prof.step()

            time.sleep(1)
            files = [
                (k, v)
                for k, v in mock_server.ctx.items()
                if k.startswith("storage") and "pt.trace.json" in k
            ]
            assert len(files) == 1
