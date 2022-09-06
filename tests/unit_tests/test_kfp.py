import inspect
from importlib import reload
from unittest.mock import patch

import kfp
import wandb
from kfp.components import InputPath, OutputPath, create_component_from_func
from kfp.components._structures import InputSpec, OutputSpec
from wandb.integration.kfp import unpatch_kfp, wandb_log


def test_get_noop_decorator_if_patching_fails():
    with patch("kfp.components._python_op.create_component_from_func", None):
        reload(wandb.integration.kfp)
        from wandb.integration.kfp import wandb_log

        # Note: I would prefer to just check for a _noop flag, but I'm not sure how to do this
        # given KFP's design.  This test is a compromise...
        _noop_string = "NOTE: Because patching failed, this decorator is a no-op."
        assert (
            _noop_string in wandb_log.__doc__
        ), "@wandb_log is not a no-op even though some functions were not able to be patched"

    assert kfp.components is not None


def test_noop_decorator_does_not_modify_inputs():
    with patch("kfp.components._python_op", None):
        reload(wandb.integration.kfp)
        from wandb.integration.kfp import wandb_log

        @wandb_log
        def train_model(
            x_train_path: InputPath("np_array"),  # noqa: F821
            y_train_path: InputPath("np_array"),  # noqa: F821
            model_path: OutputPath("sklearn_model"),  # noqa: F821
        ):
            import joblib
            import numpy as np
            from sklearn.ensemble import RandomForestClassifier

            with open(x_train_path, "rb") as f:
                x_train = np.load(f)

            with open(y_train_path, "rb") as f:
                y_train = np.load(f)

            model = RandomForestClassifier()
            model.fit(x_train, y_train)

            joblib.dump(model, model_path)

        assert train_model.__annotations__["x_train_path"].type == "np_array"
        assert train_model.__annotations__["y_train_path"].type == "np_array"
        assert train_model.__annotations__["model_path"].type == "sklearn_model"


def test_correct_annotations_and_signature():
    @wandb_log
    def add(a: float, b: float) -> float:
        return a + b

    def add2(a: float, b: float) -> float:
        return a + b

    assert add.__annotations__["a"] is add2.__annotations__["a"] is float
    assert add.__annotations__["b"] is add.__annotations__["b"] is float
    assert add.__annotations__["return"] is add2.__annotations__["return"] is float
    assert isinstance(add.__annotations__["mlpipeline_ui_metadata_path"], OutputPath)
    assert hasattr(add, "__signature__"), "Signature was not applied"


def test_decorator_does_not_modify_inputs():
    @wandb_log
    def train_model(
        x_train_path: InputPath("np_array"),  # noqa: F821
        y_train_path: InputPath("np_array"),  # noqa: F821
        model_path: OutputPath("sklearn_model"),  # noqa: F821
    ):
        import joblib
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier

        with open(x_train_path, "rb") as f:
            x_train = np.load(f)

        with open(y_train_path, "rb") as f:
            y_train = np.load(f)

        model = RandomForestClassifier()
        model.fit(x_train, y_train)

        joblib.dump(model, model_path)

    assert train_model.__annotations__["x_train_path"].type == "np_array"
    assert train_model.__annotations__["y_train_path"].type == "np_array"
    assert train_model.__annotations__["model_path"].type == "sklearn_model"


def test_valid_created_component():
    @wandb_log
    def add(a: float, b: float) -> float:
        return a + b

    def add2(a: float, b: float) -> float:
        return a + b

    add = create_component_from_func(add)
    add2 = create_component_from_func(add2)

    add_task = add(1, 2)
    add2_task = add2(1, 2)
    add_task_spec = add_task.component_ref.spec
    add2_task_spec = add2_task.component_ref.spec

    assert add_task_spec.inputs == [InputSpec("a", "Float"), InputSpec("b", "Float")]
    assert add_task_spec.outputs == [
        OutputSpec("mlpipeline_ui_metadata", None),
        OutputSpec("Output", "Float"),
    ]
    assert add2_task_spec.inputs == [InputSpec("a", "Float"), InputSpec("b", "Float")]
    assert add2_task_spec.outputs == [OutputSpec("Output", "Float")]


def test_unpatching():
    assert (
        inspect.getmodule(kfp.components._python_op.create_component_from_func)
        is wandb.integration.kfp.kfp_patch
    )
    assert (
        inspect.getmodule(kfp.components._python_op._get_function_source_definition)
        is wandb.integration.kfp.kfp_patch
    )
    assert (
        inspect.getmodule(kfp.components._python_op.strip_type_hints)
        is wandb.integration.kfp.kfp_patch
    )

    unpatch_kfp()

    assert (
        inspect.getmodule(kfp.components._python_op.create_component_from_func)
        is kfp.components._python_op
    )
    assert (
        inspect.getmodule(kfp.components._python_op._get_function_source_definition)
        is kfp.components._python_op
    )
    assert (
        inspect.getmodule(kfp.components._python_op.strip_type_hints)
        is kfp.components._python_op
    )
