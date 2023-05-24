import torch
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
import pytorch_lightning as pl


# Define the LightningModule
class MyModel(pl.LightningModule):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(784, 10)

    def forward(self, x):
        x = x.view(x.size(0), -1)
        x = self.fc(x)
        return x

    def training_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self.forward(x)
        loss = nn.functional.cross_entropy(y_hat, y)
        self.log("train_loss", loss)
        return loss

    def configure_optimizers(self):
        return torch.optim.SGD(self.parameters(), lr=0.001)


# Prepare data
transform = transforms.Compose(
    [transforms.ToTensor(), transforms.Normalize((0.5,), (0.5,))]
)
train_dataset = datasets.MNIST("mnist/", train=True, transform=transform, download=True)
train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)

# Initialize the LightningModule
model = MyModel()

# Create multiple loggers
tensorboard_logger = pl.loggers.TensorBoardLogger("logs/", name="my_model")
csv_logger = pl.loggers.CSVLogger("logs/", name="my_model")

# Create a Trainer instance with multiple loggers
trainer = pl.Trainer(
    max_epochs=5, accelerator="auto", logger=[tensorboard_logger, csv_logger]
)  # Set max_epochs and gpus according to your system

# Train the model
trainer.fit(model, train_loader)
