import wandb
import torch.nn as nn
import torch.nn.functional as F
import mlflow


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 6, 5)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(6, 16, 5)
        self.fc1 = nn.Linear(16 * 5 * 5, 120)
        self.fc2 = nn.Linear(120, 84)
        self.fc3 = nn.Linear(84, 10)

    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = torch.flatten(x, 1)  # flatten all dimensions except batch
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)
        return x


# artifact = wandb.Artifact("test-artifact", "model")

# pytorch_model = Net()
# wb_model = wandb.Model(pytorch_model)
# artifact.add(wb_model, "dummy-model")

# print(artifact.manifest.entries)

# wb_model_2 = artifact.get("dummy-model")

# assert wb_model == wb_model_2

# pytorch_model = wb_model_2.get_model(flavor="pytorch")


pytorch_model = Net()
target_dir = "./models/test_model_1"
mlflow.pytorch.save_model(pytorch_model, target_dir)

pytorch_model_2 = mlflow.pytorch.load_model(target_dir)

print("model 1:")
print(pytorch_model)

print("model 2:")
print(pytorch_model_2)
