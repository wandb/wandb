import os
import random

import kfp
import kfp.dsl as dsl
import wandb
from kfp import components
from kubernetes.client.models import V1EnvVar
from wandb.integration.kfp import wandb_log
from wandb_probe import wandb_probe_package


def add_wandb_env_variables(op):
    env = {
        "WANDB_API_KEY": os.getenv("WANDB_API_KEY"),
        "WANDB_BASE_URL": os.getenv("WANDB_BASE_URL"),
        "WANDB_KUBEFLOW_URL": os.getenv("WANDB_KUBEFLOW_URL"),
        "WANDB_PROJECT": "wandb_kfp_integration_test",
    }

    for name, value in env.items():
        op = op.add_env_variable(V1EnvVar(name, value))
    return op


@wandb_log
def setup_data(
    train_dataset_path: components.OutputPath("tensor"),  # noqa: F821
    test_dataset_path: components.OutputPath("tensor"),  # noqa: F821
):
    import torch
    from torchvision import datasets, transforms

    transform = transforms.Compose(
        [transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))]
    )
    train_dataset = datasets.FakeData(
        size=2000, image_size=(1, 28, 28), num_classes=10, transform=transform
    )
    test_dataset = datasets.FakeData(
        size=2000, image_size=(1, 28, 28), num_classes=10, transform=transform
    )

    torch.save(train_dataset, train_dataset_path)
    torch.save(test_dataset, test_dataset_path)


@wandb_log
def setup_dataloaders(
    train_dataset_path: components.InputPath("tensor"),  # noqa: F821
    test_dataset_path: components.InputPath("tensor"),  # noqa: F821
    train_dataloader_path: components.OutputPath("dataloader"),  # noqa: F821
    test_dataloader_path: components.OutputPath("dataloader"),  # noqa: F821
    batch_size: int = 32,
):
    import torch

    train_dataset = torch.load(train_dataset_path)
    test_dataset = torch.load(test_dataset_path)

    train_loader = torch.utils.data.DataLoader(
        train_dataset,
        batch_size=batch_size,
    )
    test_loader = torch.utils.data.DataLoader(
        test_dataset,
        batch_size=batch_size,
    )

    torch.save(train_loader, train_dataloader_path)
    torch.save(test_loader, test_dataloader_path)


@wandb_log
def train_model(
    train_dataloader_path: components.InputPath("dataloader"),  # noqa: F821
    test_dataloader_path: components.InputPath("dataloader"),  # noqa: F821
    model_path: components.OutputPath("pytorch_model"),  # noqa: F821
    seed: int = 1337,
    use_cuda: bool = False,
    lr: float = 1.0,
    gamma: float = 0.7,
    epochs: int = 1,
    log_interval: int = 10,
    dry_run: bool = False,
    save_model: bool = False,
):
    import torch
    import torch.nn as nn
    import torch.nn.functional as F  # noqa: N812
    import torch.optim as optim
    from torch.optim.lr_scheduler import StepLR

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = nn.Conv2d(1, 32, 3, 1)
            self.conv2 = nn.Conv2d(32, 64, 3, 1)
            self.dropout1 = nn.Dropout(0.25)
            self.dropout2 = nn.Dropout(0.5)
            self.fc1 = nn.Linear(9216, 128)
            self.fc2 = nn.Linear(128, 10)

        def forward(self, x):
            x = self.conv1(x)
            x = F.relu(x)
            x = self.conv2(x)
            x = F.relu(x)
            x = F.max_pool2d(x, 2)
            x = self.dropout1(x)
            x = torch.flatten(x, 1)
            x = self.fc1(x)
            x = F.relu(x)
            x = self.dropout2(x)
            x = self.fc2(x)
            output = F.log_softmax(x, dim=1)
            return output

    def train(model, device, train_loader, optimizer, epoch, log_interval, dry_run):
        model.train()
        for batch_idx, (data, target) in enumerate(train_loader):
            data, target = data.to(device), target.to(device)
            optimizer.zero_grad()
            output = model(data)
            loss = F.nll_loss(output, target)
            loss.backward()
            optimizer.step()
            if batch_idx % log_interval == 0:
                wandb.log(
                    {"epoch": epoch, "step": batch_idx * len(data), "loss": loss.item()}
                )
                if dry_run:
                    break

    def test(model, device, test_loader):
        model.eval()
        test_loss = 0
        correct = 0
        with torch.no_grad():
            for data, target in test_loader:
                data, target = data.to(device), target.to(device)
                output = model(data)
                test_loss += F.nll_loss(
                    output, target, reduction="sum"
                ).item()  # sum up batch loss
                pred = output.argmax(
                    dim=1, keepdim=True
                )  # get the index of the max log-probability
                correct += pred.eq(target.view_as(pred)).sum().item()

        test_loss /= len(test_loader.dataset)
        wandb.log(
            {"test_loss": test_loss, "accuracy": correct / len(test_loader.dataset)}
        )

    torch.manual_seed(seed)
    train_loader = torch.load(train_dataloader_path)
    test_loader = torch.load(test_dataloader_path)

    device = torch.device("cuda" if use_cuda else "cpu")
    model = Net()
    model.to(device)
    optimizer = optim.Adadelta(model.parameters(), lr=lr)
    scheduler = StepLR(optimizer, step_size=1, gamma=gamma)
    for epoch in range(1, epochs + 1):
        train(
            model,
            device,
            train_loader,
            optimizer,
            epoch,
            log_interval,
            dry_run,
        )
        test(model, device, test_loader)
        scheduler.step()

    if save_model:
        torch.save(model.state_dict(), model_path)


packages_to_install = ["torch", "torchvision"]
# probe wandb dev build if needed (otherwise released wandb will be used)
wandb_package = wandb_probe_package()
if wandb_package:
    print("INFO: wandb_probe_package found:", wandb_package)
    packages_to_install.append(wandb_package)
setup_data = components.create_component_from_func(
    setup_data,
    packages_to_install=packages_to_install,
)
setup_dataloaders = components.create_component_from_func(
    setup_dataloaders,
    packages_to_install=packages_to_install,
)
train_model = components.create_component_from_func(
    train_model,
    packages_to_install=packages_to_install,
)


@dsl.pipeline(name="testing-pipeline")
def testing_pipeline(seed, save_model):
    conf = dsl.get_pipeline_conf()
    conf.add_op_transformer(add_wandb_env_variables)

    setup_data_task = setup_data()
    setup_dataloaders_task = setup_dataloaders(
        setup_data_task.outputs["train_dataset"],
        setup_data_task.outputs["test_dataset"],
        batch_size=32,
    )
    train_model_task = train_model(  # noqa: F841
        setup_dataloaders_task.outputs["train_dataloader"],
        setup_dataloaders_task.outputs["test_dataloader"],
        save_model=save_model,
    )


client = kfp.Client()
run = client.create_run_from_pipeline_func(
    testing_pipeline,
    arguments={"seed": random.randint(0, 999999), "save_model": True},
)

run.wait_for_run_completion()
