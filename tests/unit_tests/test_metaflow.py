import platform
from pathlib import Path

import pytest

if platform.system() == "Windows":
    pytest.importorskip("metaflow", reason="metaflow does not support native Windows")

import pandas as pd
from metaflow import FlowSpec, step  # noqa: I100, I202
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from wandb.integration.metaflow import wandb_log, wandb_track, wandb_use

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F  # noqa: N812
except ImportError:

    class nn:  # noqa: N801
        Module = object


def test_decoration_class():
    @wandb_log(datasets=True, models=True, others=False)
    class WandbExampleFlowDecoClass(FlowSpec):
        @step
        def start(self):
            self.next(self.middle)

        @step
        def middle(self):
            self.next(self.end)

        @step
        def end(self):
            pass

    assert hasattr(WandbExampleFlowDecoClass.start, "_base_func")
    assert hasattr(WandbExampleFlowDecoClass.middle, "_base_func")
    assert hasattr(WandbExampleFlowDecoClass.end, "_base_func")

    assert WandbExampleFlowDecoClass.start._kwargs == {
        "datasets": True,
        "models": True,
        "others": False,
        "settings": None,
    }
    assert WandbExampleFlowDecoClass.start._kwargs == {
        "datasets": True,
        "models": True,
        "others": False,
        "settings": None,
    }
    assert WandbExampleFlowDecoClass.start._kwargs == {
        "datasets": True,
        "models": True,
        "others": False,
        "settings": None,
    }


def test_decoration_method():
    class WandbExampleFlowDecoClass(FlowSpec):
        @wandb_log(datasets=True, models=True, others=True)
        @step
        def start(self):
            self.next(self.middle)

        @step
        def middle(self):
            self.next(self.end)

        @wandb_log(datasets=True, models=True, others=True)
        @step
        def end(self):
            pass

    assert hasattr(WandbExampleFlowDecoClass.start, "_base_func")
    assert not hasattr(WandbExampleFlowDecoClass.middle, "_base_func")
    assert hasattr(WandbExampleFlowDecoClass.end, "_base_func")

    assert WandbExampleFlowDecoClass.start._kwargs == {
        "datasets": True,
        "models": True,
        "others": True,
        "settings": None,
    }
    assert not hasattr(WandbExampleFlowDecoClass.middle, "_base_func")
    assert WandbExampleFlowDecoClass.start._kwargs == {
        "datasets": True,
        "models": True,
        "others": True,
        "settings": None,
    }


def test_decoration_both_overwrite():
    @wandb_log(datasets=True, models=True, others=True)
    class WandbExampleFlowDecoClass(FlowSpec):
        @wandb_log(datasets=False, models=False, others=False)
        @step
        def start(self):
            self.next(self.middle)

        @step
        def middle(self):
            self.next(self.end)

        @wandb_log(datasets=True, models=True, others=True)
        @step
        def end(self):
            pass

    assert hasattr(WandbExampleFlowDecoClass.start, "_base_func")
    assert hasattr(WandbExampleFlowDecoClass.middle, "_base_func")
    assert hasattr(WandbExampleFlowDecoClass.end, "_base_func")

    assert WandbExampleFlowDecoClass.start._kwargs == {
        "datasets": False,
        "models": False,
        "others": False,
        "settings": None,
    }
    assert WandbExampleFlowDecoClass.middle._kwargs == {
        "datasets": True,
        "models": True,
        "others": True,
        "settings": None,
    }
    assert WandbExampleFlowDecoClass.end._kwargs == {
        "datasets": True,
        "models": True,
        "others": True,
        "settings": None,
    }


def test_track_dataframe():
    df = pd.read_csv(
        "https://gist.githubusercontent.com/tijptjik/9408623/raw/b237fa5848349a14a14e5d4107dc7897c21951f5/wine.csv"
    )
    assert wandb_track("df", df, testing=True, datasets=True) == "pd.DataFrame"
    assert wandb_track("df", df, testing=True, datasets=False) is None


def test_track_path():
    path = Path()
    assert wandb_track("path", path, testing=True, datasets=True) == "Path"
    assert wandb_track("path", path, testing=True, datasets=False) is None


def test_track_sklearn_model():
    rf_clf = RandomForestClassifier()
    assert wandb_track("rf_clf", rf_clf, testing=True, models=True) == "BaseEstimator"
    assert wandb_track("rf_clf", rf_clf, testing=True, models=False) is None

    gb_clf = GradientBoostingClassifier()
    assert wandb_track("gb_clf", gb_clf, testing=True, models=True) == "BaseEstimator"
    assert wandb_track("gb_clf", gb_clf, testing=True, models=False) is None


def test_track_pytorch_model():
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

    model = Net()
    assert wandb_track("model", model, testing=True, models=True) == "nn.Module"
    assert wandb_track("model", model, testing=True, models=False) is None


def test_track_other():
    def func():
        pass

    assert wandb_track("func", func, testing=True, others=True) == "generic"
    assert wandb_track("func", func, testing=True, others=False) is None


def test_track_scalar():
    bool_value = False
    float_value = 1.1
    int_value = 1
    str_value = "wandb"
    set_value = {1, 2, 3}
    list_value = [4, 5, 6]
    dict_value = {
        "bool": bool_value,
        "float": float_value,
        "int": int_value,
        "str": str_value,
        "set": set_value,
        "list": list_value,
    }

    assert wandb_track("bool", bool_value, testing=True) == "scalar"
    assert wandb_track("float", float_value, testing=True) == "scalar"
    assert wandb_track("int", int_value, testing=True) == "scalar"
    assert wandb_track("str", str_value, testing=True) == "scalar"
    assert wandb_track("set", set_value, testing=True) == "scalar"
    assert wandb_track("list", list_value, testing=True) == "scalar"
    assert wandb_track("dict", dict_value, testing=True) == "scalar"


def test_use_datasets():
    df = pd.read_csv(
        "https://gist.githubusercontent.com/tijptjik/9408623/raw/b237fa5848349a14a14e5d4107dc7897c21951f5/wine.csv"
    )
    assert wandb_use("df", df, testing=True, datasets=True) == "datasets"
    assert wandb_use("df", df, testing=True, datasets=False) is None

    path = Path()
    assert wandb_use("path", path, testing=True, datasets=True) == "datasets"
    assert wandb_use("path", path, testing=True, datasets=False) is None


def test_use_models():
    rf_clf = RandomForestClassifier()
    assert wandb_use("rf_clf", rf_clf, testing=True, models=True) == "models"
    assert wandb_use("rf_clf", rf_clf, testing=True, models=False) is None

    gb_clf = GradientBoostingClassifier()
    assert wandb_use("gb_clf", gb_clf, testing=True, models=True) == "models"
    assert wandb_use("gb_clf", gb_clf, testing=True, models=False) is None

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

    model = Net()
    assert wandb_use("model", model, testing=True, models=True) == "models"
    assert wandb_use("model", model, testing=True, models=False) is None


def test_use_others():
    def func():
        pass

    assert wandb_use("func", func, testing=True, others=True) == "others"
    assert wandb_use("func", func, testing=True, others=False) is None
