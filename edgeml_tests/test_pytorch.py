import wandb
import pytest
import torch
import glob
import logging
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.tensorboard import SummaryWriter


class ConvNet(nn.Module):
    def __init__(self):
        super(ConvNet, self).__init__()
        self.conv1 = nn.Conv2d(1, 10, kernel_size=5)
        self.conv2 = nn.Conv2d(10, 20, kernel_size=5)
        self.conv2_drop = nn.Dropout2d()
        self.fc1 = nn.Linear(320, 50)
        self.fc2 = nn.Linear(50, 10)

    def forward(self, x):
        x = F.relu(F.max_pool2d(self.conv1(x), 2))
        x = F.relu(F.max_pool2d(self.conv2_drop(self.conv2(x)), 2))
        x = x.view(-1, 320)
        x = F.relu(self.fc1(x))
        x = F.dropout(x, training=self.training)
        x = self.fc2(x)
        return F.log_softmax(x, dim=1)


@pytest.mark.mocked_run_manager()
def test_tensorboard_pytorch(wandb_init_run, caplog):
    caplog.set_level(logging.INFO)
    writer = SummaryWriter()
    wandb.tensorboard.patch(tensorboardX=False)
    net = ConvNet()
    wandb.watch(net, log_freq=1)
    for i in range(3):
        output = net(torch.ones((64, 1, 28, 28)))
        loss = F.mse_loss(output, torch.ones((64, 10)))
        output.backward(torch.ones(64, 10))
        writer.add_scalar("loss", loss / 64, i+1)
        writer.add_image("example", torch.ones((1, 28, 28)), i+1)
        # TODO: There's a race here and it's gross
        assert(len(wandb_init_run.history.row) in (4, 8, 12))
    wandb_init_run.run_manager.test_shutdown()
    print("DIR: ", glob.glob(wandb_init_run.dir + "/*"),
          glob.glob(wandb_init_run.dir + "/**/*"))
    assert len(glob.glob(wandb_init_run.dir + "/*.tfevents.*")) == 1
    assert(len(wandb_init_run.history.rows) == 4)
    assert list(wandb_init_run.history.rows[0].keys()) == ['gradients/fc2.bias',
                                                           'gradients/fc2.weight',
                                                           'gradients/fc1.bias',
                                                           'gradients/fc1.weight',
                                                           'gradients/conv2.weight',
                                                           'gradients/conv2.bias',
                                                           'gradients/conv1.weight',
                                                           'gradients/conv1.bias',
                                                           '_runtime',
                                                           '_timestamp',
                                                           '_step']
    assert list(wandb_init_run.history.rows[-1].keys()) == ['global_step',
                                                            '_timestamp', 'loss', 'example', '_runtime', '_step']
