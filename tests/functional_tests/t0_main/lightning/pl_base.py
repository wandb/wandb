import torch
from lightning import LightningModule
from torch.utils.data import Dataset


class RandomDataset(Dataset):
    def __init__(self, size, num_samples):
        self.len = num_samples
        self.data = torch.randn(num_samples, size)

    def __getitem__(self, index):
        return self.data[index]

    def __len__(self):
        return self.len


class BoringModel(LightningModule):
    def __init__(self):
        super().__init__()
        self.layer = torch.nn.Linear(32, 2)
        self.training_step_outputs = []
        self.validation_step_outputs = []
        self.test_step_outputs = []

    def forward(self, x):
        return self.layer(x)

    def loss(self, batch, prediction):
        # An arbitrary loss to have a loss that updates the model weights during `Trainer.fit` calls
        return torch.nn.functional.mse_loss(prediction, torch.ones_like(prediction))

    def configure_optimizers(self):
        optimizer = torch.optim.SGD(self.layer.parameters(), lr=0.1)
        lr_scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=1)
        return [optimizer], [lr_scheduler]

    def training_step(self, batch, _):
        output = self.layer(batch)
        loss = self.loss(batch, output)
        self.log("loss", loss)
        self.training_step_outputs.append(loss)
        return loss

    def on_train_epoch_end(self):
        _ = torch.stack(self.training_step_outputs).mean()
        self.training_step_outputs.clear()  # free memory

    def validation_step(self, batch, _):
        output = self.layer(batch)
        loss = self.loss(batch, output)
        self.validation_step_outputs.append(loss)
        return loss

    def on_validation_epoch_end(self) -> None:
        _ = torch.stack(self.validation_step_outputs).mean()
        self.validation_step_outputs.clear()  # free memory

    def test_step(self, batch, _):
        output = self.layer(batch)
        loss = self.loss(batch, output)
        self.log("fake_test_acc", loss)
        self.test_step_outputs.append(loss)
        return loss

    def on_test_epoch_end(self) -> None:
        _ = torch.stack(self.test_step_outputs).mean()
        self.test_step_outputs.clear()  # free memory
