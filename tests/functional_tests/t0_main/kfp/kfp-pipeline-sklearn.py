import os
import random
from typing import NamedTuple

import kfp
import kfp.dsl as dsl
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
def preprocess_data(
    X_train_path: components.OutputPath("np_array"),  # noqa: F821,N803
    X_test_path: components.OutputPath("np_array"),  # noqa: F821,N803
    y_train_path: components.OutputPath("np_array"),  # noqa: F821
    y_test_path: components.OutputPath("np_array"),  # noqa: F821
    seed: int = 1337,
):
    import numpy as np
    from sklearn import datasets
    from sklearn.model_selection import train_test_split

    X, y = datasets.load_iris(return_X_y=True)  # noqa: N806
    X_train, X_test, y_train, y_test = train_test_split(  # noqa: N806
        X, y, test_size=0.2, random_state=seed
    )

    with open(X_train_path, "wb") as f:
        np.save(f, X_train)

    with open(y_train_path, "wb") as f:
        np.save(f, y_train)

    with open(X_test_path, "wb") as f:
        np.save(f, X_test)

    with open(y_test_path, "wb") as f:
        np.save(f, y_test)


@wandb_log
def train_model(
    X_train_path: components.InputPath("np_array"),  # noqa: F821,N803
    y_train_path: components.InputPath("np_array"),  # noqa: F821,N803
    model_path: components.OutputPath("sklearn_model"),  # noqa: F821
):
    import joblib
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier

    with open(X_train_path, "rb") as f:
        X_train = np.load(f)  # noqa: N806

    with open(y_train_path, "rb") as f:
        y_train = np.load(f)

    model = RandomForestClassifier()
    model.fit(X_train, y_train)

    joblib.dump(model, model_path)


@wandb_log
def test_model(
    X_test_path: components.InputPath("np_array"),  # noqa: F821,N803
    y_test_path: components.InputPath("np_array"),  # noqa: F821
    model_path: components.InputPath("sklearn_model"),  # noqa: F821
) -> NamedTuple(
    "Output", [("accuracy", float), ("precision", float), ("recall", float)]
):
    from collections import namedtuple

    import joblib
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier  # noqa: F401
    from sklearn.metrics import accuracy_score, precision_score, recall_score

    with open(X_test_path, "rb") as f:
        X_test = np.load(f)  # noqa: N806

    with open(y_test_path, "rb") as f:
        y_test = np.load(f)

    model = joblib.load(model_path)
    preds = model.predict(X_test)

    accuracy = accuracy_score(y_test, preds)
    precision = precision_score(y_test, preds, average="micro")
    recall = recall_score(y_test, preds, average="micro")

    output = namedtuple("Output", ["accuracy", "precision", "recall"])
    return output(accuracy, precision, recall)


packages_to_install = ["scikit-learn"]
# probe wandb dev build if needed (otherwise released wandb will be used)
wandb_package = wandb_probe_package()
if wandb_package:
    print("INFO: wandb_probe_package found:", wandb_package)
    packages_to_install.append(wandb_package)
preprocess_data = components.create_component_from_func(
    preprocess_data,
    packages_to_install=packages_to_install,
)
train_model = components.create_component_from_func(
    train_model,
    packages_to_install=packages_to_install,
)
test_model = components.create_component_from_func(
    test_model,
    packages_to_install=packages_to_install,
)


@dsl.pipeline(name="testing-pipeline")
def testing_pipeline(seed: int):
    conf = dsl.get_pipeline_conf()
    conf.add_op_transformer(add_wandb_env_variables)

    preprocess_data_task = preprocess_data(seed)
    train_model_task = train_model(
        preprocess_data_task.outputs["X_train"], preprocess_data_task.outputs["y_train"]
    )
    test_model_task = test_model(  # noqa: F841
        preprocess_data_task.outputs["X_test"],
        preprocess_data_task.outputs["y_test"],
        train_model_task.output,
    )


client = kfp.Client()
run = client.create_run_from_pipeline_func(
    testing_pipeline,
    arguments={"seed": random.randint(0, 999999)},
)

run.wait_for_run_completion()
