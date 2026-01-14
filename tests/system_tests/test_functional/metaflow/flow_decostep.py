"""Test Metaflow Flow integration"""

import os
import pathlib

import pandas as pd
import wandb
from metaflow import FlowSpec, Parameter, step
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from wandb.integration.metaflow import wandb_log

os.environ["METAFLOW_USER"] = "test_user"
os.environ["USER"] = os.environ["METAFLOW_USER"]


class WandbExampleFlowDecoStep(FlowSpec):
    # Not obvious how to support metaflow.IncludeFile
    seed = Parameter("seed", default=1337)
    test_size = Parameter("test_size", default=0.2)
    raw_data = Parameter(
        "raw_data",
        default=pathlib.Path(__file__).parent / "wine.csv",
        help="path to the raw data",
    )

    @wandb_log(datasets=True, models=True)
    @step
    def start(self):
        self.raw_df = pd.read_csv(self.raw_data)
        self.next(self.split_data)

    @wandb_log(datasets=True)
    @step
    def split_data(self):
        X = self.raw_df.drop("Wine", axis=1)  # noqa: N806
        y = self.raw_df[["Wine"]]
        self.X_train, self.X_test, self.y_train, self.y_test = train_test_split(
            X, y, test_size=self.test_size, random_state=self.seed
        )
        self.next(self.train)

    @wandb_log
    @step
    def train(self):
        self.clf = RandomForestClassifier(
            n_estimators=2,
            max_depth=2,
            random_state=self.seed,
        )
        self.clf.fit(self.X_train, self.y_train)
        self.next(self.end)

    @wandb_log()
    @step
    def end(self):
        self.preds = self.clf.predict(self.X_test)
        self.accuracy = accuracy_score(self.y_test, self.preds)


if __name__ == "__main__":
    wandb.setup()
    WandbExampleFlowDecoStep()
