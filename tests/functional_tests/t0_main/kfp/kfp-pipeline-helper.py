import os
import random
from typing import NamedTuple

import kfp
import kfp.dsl as dsl
from kfp import components
from kubernetes.client.models import V1EnvVar
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


def preprocess_data(
    X_train_path: components.OutputPath("np_array"),  # noqa: F821,N803
    X_test_path: components.OutputPath("np_array"),  # noqa: F821,N803
    y_train_path: components.OutputPath("np_array"),  # noqa: F821
    y_test_path: components.OutputPath("np_array"),  # noqa: F821
    mlpipeline_ui_metadata_path: components.OutputPath(),
    seed: int = 1337,
):
    import json

    import numpy as np
    import wandb
    from sklearn import datasets
    from sklearn.model_selection import train_test_split

    def add_wandb_visualization(run, mlpipeline_ui_metadata_path):
        """NOTE: To use this, you must modify your component to have an output called `mlpipeline_ui_metadata_path` AND call `wandb.init` yourself inside that component.

        Example usage:

        def my_component(..., mlpipeline_ui_metadata_path: OutputPath()):
            import wandb
            from wandb.integration.kfp.helpers import add_wandb_visualization

            with wandb.init() as run:
                add_wandb_visualization(run, mlpipeline_ui_metadata_path)

                ... # the rest of your code here
        """

        def get_iframe_html(run):
            return f'<iframe src="{run.url}?kfp=true" style="border:none;width:100%;height:100%;min-width:900px;min-height:600px;"></iframe>'

        iframe_html = get_iframe_html(run)
        metadata = {
            "outputs": [
                {"type": "markdown", "storage": "inline", "source": iframe_html}
            ]
        }

        with open(mlpipeline_ui_metadata_path, "w") as metadata_file:
            json.dump(metadata, metadata_file)

    with wandb.init() as run:
        add_wandb_visualization(run, mlpipeline_ui_metadata_path)

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


def train_model(
    X_train_path: components.InputPath("np_array"),  # noqa: F821,N803
    y_train_path: components.InputPath("np_array"),  # noqa: F821,N803
    model_path: components.OutputPath("sklearn_model"),  # noqa: F821
    mlpipeline_ui_metadata_path: components.OutputPath(),
):
    import json

    import joblib
    import numpy as np
    import wandb
    from sklearn.ensemble import RandomForestClassifier

    def add_wandb_visualization(run, mlpipeline_ui_metadata_path):
        """NOTE: To use this, you must modify your component to have an output called `mlpipeline_ui_metadata_path` AND call `wandb.init` yourself inside that component.

        Example usage:

        def my_component(..., mlpipeline_ui_metadata_path: OutputPath()):
            import wandb
            from wandb.integration.kfp.helpers import add_wandb_visualization

            with wandb.init() as run:
                add_wandb_visualization(run, mlpipeline_ui_metadata_path)

                ... # the rest of your code here
        """

        def get_iframe_html(run):
            return f'<iframe src="{run.url}?kfp=true" style="border:none;width:100%;height:100%;min-width:900px;min-height:600px;"></iframe>'

        iframe_html = get_iframe_html(run)
        metadata = {
            "outputs": [
                {"type": "markdown", "storage": "inline", "source": iframe_html}
            ]
        }

        with open(mlpipeline_ui_metadata_path, "w") as metadata_file:
            json.dump(metadata, metadata_file)

    with wandb.init() as run:
        add_wandb_visualization(run, mlpipeline_ui_metadata_path)

        with open(X_train_path, "rb") as f:
            X_train = np.load(f)  # noqa: N806

        with open(y_train_path, "rb") as f:
            y_train = np.load(f)

        model = RandomForestClassifier()
        model.fit(X_train, y_train)

        joblib.dump(model, model_path)


def test_model(
    X_test_path: components.InputPath("np_array"),  # noqa: F821,N803
    y_test_path: components.InputPath("np_array"),  # noqa: F821
    model_path: components.InputPath("sklearn_model"),  # noqa: F821
    mlpipeline_ui_metadata_path: components.OutputPath(),
) -> NamedTuple(
    "Output", [("accuracy", float), ("precision", float), ("recall", float)]
):
    import json
    from collections import namedtuple

    import joblib
    import numpy as np
    import wandb
    from sklearn.ensemble import RandomForestClassifier  # noqa: F401
    from sklearn.metrics import accuracy_score, precision_score, recall_score

    def add_wandb_visualization(run, mlpipeline_ui_metadata_path):
        """NOTE: To use this, you must modify your component to have an output called `mlpipeline_ui_metadata_path` AND call `wandb.init` yourself inside that component.

        Example usage:

        def my_component(..., mlpipeline_ui_metadata_path: OutputPath()):
            import wandb
            from wandb.integration.kfp.helpers import add_wandb_visualization

            with wandb.init() as run:
                add_wandb_visualization(run, mlpipeline_ui_metadata_path)

                ... # the rest of your code here
        """

        def get_iframe_html(run):
            return f'<iframe src="{run.url}?kfp=true" style="border:none;width:100%;height:100%;min-width:900px;min-height:600px;"></iframe>'

        iframe_html = get_iframe_html(run)
        metadata = {
            "outputs": [
                {"type": "markdown", "storage": "inline", "source": iframe_html}
            ]
        }

        with open(mlpipeline_ui_metadata_path, "w") as metadata_file:
            json.dump(metadata, metadata_file)

    with wandb.init() as run:
        add_wandb_visualization(run, mlpipeline_ui_metadata_path)

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


packages_to_install = ["scikit-learn", "wandb"]
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
