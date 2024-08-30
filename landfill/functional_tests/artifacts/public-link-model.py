import torch
import torch.nn as nn
import torch.nn.functional as F  # noqa

import wandb
from wandb.errors import CommError


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


def main():
    # create an artifact
    # call .wait() to get a Public Artifact bound to it
    # and then do link on that artifact
    run = wandb.init()
    with open("my-dataset.txt", "w") as fp:
        fp.write("this-is-data")
    try:
        artifact = run.use_artifact("my-art-name:latest", "my-art-type")
    except CommError:
        artifact = wandb.Artifact("my-art-name", "my-art-type")
        artifact.add_file("my-dataset.txt")
        artifact = run.log_artifact(artifact)
        artifact.wait()
    artifact.link("project/test_portfolio_public_link_test", aliases="best")
    run.finish()


if __name__ == "__main__":
    main()
