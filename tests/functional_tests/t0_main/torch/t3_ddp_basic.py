# based on the following example: https://github.com/pytorch/examples/blob/main/distributed/ddp/main.py
import os

import torch
import torch.distributed as dist
import torch.multiprocessing as mp
import torch.nn as nn
import torch.optim as optim
import wandb
from torch.nn.parallel import DistributedDataParallel


def setup(rank, world_size):
    os.environ["MASTER_ADDR"] = "localhost"
    os.environ["MASTER_PORT"] = "12355"

    # initialize the process group
    dist.init_process_group("gloo", rank=rank, world_size=world_size)


def cleanup():
    dist.destroy_process_group()


class ToyModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.net1 = nn.Linear(10, 10)
        self.relu = nn.ReLU()
        self.net2 = nn.Linear(10, 5)

    def forward(self, x):
        return self.net2(self.relu(self.net1(x)))


def demo_basic(rank, world_size):
    print(f"Running basic DDP example on rank {rank}.")
    setup(rank, world_size)

    if torch.cuda.is_available():
        device = rank
        device_ids = [rank]
    else:
        device = torch.device("cpu")
        device_ids = []

    # create model and move it to GPU with id rank
    model = ToyModel().to(device)
    ddp_model = DistributedDataParallel(model, device_ids=device_ids)

    with wandb.init(group="ddp-basic") as run:
        run.watch(models=ddp_model, log_freq=1, log_graph=True)

        loss_fn = nn.MSELoss()
        optimizer = optim.SGD(ddp_model.parameters(), lr=0.001)

        for _ in range(3):
            optimizer.zero_grad()
            outputs = ddp_model(torch.randn(20, 10))
            labels = torch.randn(20, 5).to(device)
            loss = loss_fn(outputs, labels)
            run.log({"loss": loss})
        loss.backward()
        optimizer.step()

    cleanup()


if __name__ == "__main__":
    wandb.require("service")
    world_size = 2
    mp.spawn(
        demo_basic,
        args=(world_size,),
        nprocs=world_size,
        join=True,
    )
