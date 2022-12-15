"""
Test Metaflow Flow integration
"""

import os

import pandas as pd
from metaflow import FlowSpec, Parameter, step
from sklearn.ensemble import (  # noqa: F401
    GradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from wandb.integration.metaflow import wandb_log

os.environ["WANDB_SILENT"] = "true"
os.environ["METAFLOW_USER"] = "test_user"


def setup_model(name, *args, **kwargs):
    return eval(name)(*args, **kwargs)


@wandb_log
class WandbForeachFlow(FlowSpec):
    seed = Parameter("seed", default=1337)
    test_size = Parameter("test_size", default=0.2)
    raw_data = Parameter(
        "raw_data",
        default="https://gist.githubusercontent.com/tijptjik/9408623/raw/b237fa5848349a14a14e5d4107dc7897c21951f5/wine.csv",
        help="path to the raw data",
    )

    @step
    def start(self):
        self.models = ["RandomForestClassifier", "GradientBoostingClassifier"]
        self.raw_df = pd.read_csv(self.raw_data)
        self.next(self.split_data)

    @wandb_log(datasets=True, models=True, others=True)
    @step
    def split_data(self):
        X = self.raw_df.drop("Wine", axis=1)
        y = self.raw_df[["Wine"]]
        self.X_train, self.X_test, self.y_train, self.y_test = train_test_split(
            X, y, test_size=self.test_size, random_state=self.seed
        )
        self.next(self.train, foreach="models")

    @step
    def train(self):
        self.model_name = self.input
        # self.clf = RandomForestClassifier(random_state=self.seed)
        self.clf = setup_model(self.model_name, random_state=self.seed)
        self.clf.fit(self.X_train, self.y_train)
        self.preds = self.clf.predict(self.X_test)
        self.accuracy = accuracy_score(self.y_test, self.preds)
        self.next(self.join_train)

    @step
    def join_train(self, inputs):
        self.results = [
            {
                "model_name": input.model_name,
                "preds": input.preds,
                "accuracy": input.accuracy,
            }
            for input in inputs
        ]
        self.next(self.end)

    @step
    def end(self):
        pass


if __name__ == "__main__":
    WandbForeachFlow()
