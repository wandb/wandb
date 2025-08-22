import inspect
import itertools
import textwrap
from typing import Callable, List, Mapping, Optional

import wandb

try:
    from kfp import __version__ as kfp_version
    from kfp.components import structures
    from kfp.components._components import _create_task_factory_from_component_spec
    from kfp.components._python_op import _func_to_component_spec
    from packaging.version import parse

    MIN_KFP_VERSION = "1.6.1"

    if parse(kfp_version) < parse(MIN_KFP_VERSION):
        wandb.termwarn(
            f"Your version of kfp {kfp_version} may not work.  This integration requires kfp>={MIN_KFP_VERSION}"
        )

except ImportError:
    wandb.termerror("kfp not found!  Please `pip install kfp`")

from .wandb_logging import wandb_log

decorator_code = inspect.getsource(wandb_log)
wandb_logging_extras = f"""
import typing
from typing import NamedTuple

import collections
from collections import namedtuple

import kfp
from kfp import components
from kfp.components import InputPath, OutputPath

import wandb

{decorator_code}
"""


def full_path_exists(full_func):
    def get_parent_child_pairs(full_func):
        components = full_func.split(".")
        parents, children = [], []
        for i, _ in enumerate(components[:-1], 1):
            parent = ".".join(components[:i])
            child = components[i]
            parents.append(parent)
            children.append(child)
        return zip(parents, children)

    for parent, child in get_parent_child_pairs(full_func):
        module = wandb.util.get_module(parent)
        if not module or not hasattr(module, child) or getattr(module, child) is None:
            return False
    return True


def patch(module_name, func):
    module = wandb.util.get_module(module_name)
    success = False

    full_func = f"{module_name}.{func.__name__}"
    if not full_path_exists(full_func):
        wandb.termerror(
            f"Failed to patch {module_name}.{func.__name__}!  Please check if this package/module is installed!"
        )
    else:
        wandb.patched.setdefault(module.__name__, [])
        # if already patched, do not patch again
        if [module, func.__name__] not in wandb.patched[module.__name__]:
            setattr(module, f"orig_{func.__name__}", getattr(module, func.__name__))
            setattr(module, func.__name__, func)
            wandb.patched[module.__name__].append([module, func.__name__])
        success = True

    return success


def unpatch(module_name):
    if module_name in wandb.patched:
        for module, func in wandb.patched[module_name]:
            setattr(module, func, getattr(module, f"orig_{func}"))
        wandb.patched[module_name] = []


def unpatch_kfp():
    unpatch("kfp.components")
    unpatch("kfp.components._python_op")
    unpatch("wandb.integration.kfp")


def patch_kfp():
    to_patch = [
        (
            "kfp.components",
            create_component_from_func,
        ),
        (
            "kfp.components._python_op",
            create_component_from_func,
        ),
        (
            "kfp.components._python_op",
            _get_function_source_definition,
        ),
        ("kfp.components._python_op", strip_type_hints),
    ]

    successes = []
    for module_name, func in to_patch:
        success = patch(module_name, func)
        successes.append(success)
    if not all(successes):
        wandb.termerror(
            "Failed to patch one or more kfp functions.  Patching @wandb_log decorator to no-op."
        )
        patch("wandb.integration.kfp", wandb_log)


def wandb_log(
    func=None,
    # /,  # py38 only
    log_component_file=True,
):
    """Wrap a standard python function and log to W&B.

    NOTE: Because patching failed, this decorator is a no-op.
    """
    from functools import wraps

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)


def _get_function_source_definition(func: Callable) -> str:
    """Get the source code of a function.

    This function is modified from KFP.  The original source is below:
    https://github.com/kubeflow/pipelines/blob/b6406b02f45cdb195c7b99e2f6d22bf85b12268b/sdk/python/kfp/components/_python_op.py#L300-L319.
    """
    func_code = inspect.getsource(func)

    # Function might be defined in some indented scope (e.g. in another
    # function). We need to handle this and properly dedent the function source
    # code
    func_code = textwrap.dedent(func_code)
    func_code_lines = func_code.split("\n")

    # For wandb, allow decorators (so we can use the @wandb_log decorator)
    func_code_lines = itertools.dropwhile(
        lambda x: not (x.startswith(("def", "@wandb_log"))),
        func_code_lines,
    )

    if not func_code_lines:
        raise ValueError(
            f'Failed to dedent and clean up the source of function "{func.__name__}". '
            "It is probably not properly indented."
        )

    return "\n".join(func_code_lines)


def create_component_from_func(
    func: Callable,
    output_component_file: Optional[str] = None,
    base_image: Optional[str] = None,
    packages_to_install: Optional[List[str]] = None,
    annotations: Optional[Mapping[str, str]] = None,
):
    '''Convert a Python function to a component and returns a task factory.

    The returned task factory accepts arguments and returns a task object.

    This function is modified from KFP.  The original source is below:
    https://github.com/kubeflow/pipelines/blob/b6406b02f45cdb195c7b99e2f6d22bf85b12268b/sdk/python/kfp/components/_python_op.py#L998-L1110.

    Args:
        func: The python function to convert
        base_image: Optional. Specify a custom Docker container image to use in the component. For lightweight components, the image needs to have python 3.5+. Default is the python image corresponding to the current python environment.
        output_component_file: Optional. Write a component definition to a local file. The produced component file can be loaded back by calling :code:`load_component_from_file` or :code:`load_component_from_uri`.
        packages_to_install: Optional. List of [versioned] python packages to pip install before executing the user function.
        annotations: Optional. Allows adding arbitrary key-value data to the component specification.

    Returns:
        A factory function with a strongly-typed signature taken from the python function.
        Once called with the required arguments, the factory constructs a task instance that can run the original function in a container.

    Examples:
        The function name and docstring are used as component name and description. Argument and return annotations are used as component input/output types::

            def add(a: float, b: float) -> float:
                """Return sum of two arguments"""
                return a + b


            # add_op is a task factory function that creates a task object when given arguments
            add_op = create_component_from_func(
                func=add,
                base_image="python:3.7",  # Optional
                output_component_file="add.component.yaml",  # Optional
                packages_to_install=["pandas==0.24"],  # Optional
            )

            # The component spec can be accessed through the .component_spec attribute:
            add_op.component_spec.save("add.component.yaml")

            # The component function can be called with arguments to create a task:
            add_task = add_op(1, 3)

            # The resulting task has output references, corresponding to the component outputs.
            # When the function only has a single anonymous return value, the output name is "Output":
            sum_output_ref = add_task.outputs["Output"]

            # These task output references can be passed to other component functions, constructing a computation graph:
            task2 = add_op(sum_output_ref, 5)


        :code:`create_component_from_func` function can also be used as decorator::

            @create_component_from_func
            def add_op(a: float, b: float) -> float:
                """Return sum of two arguments"""
                return a + b

        To declare a function with multiple return values, use the :code:`NamedTuple` return annotation syntax::

            from typing import NamedTuple


            def add_multiply_two_numbers(a: float, b: float) -> NamedTuple(
                "Outputs", [("sum", float), ("product", float)]
            ):
                """Return sum and product of two arguments"""
                return (a + b, a * b)


            add_multiply_op = create_component_from_func(add_multiply_two_numbers)

            # The component function can be called with arguments to create a task:
            add_multiply_task = add_multiply_op(1, 3)

            # The resulting task has output references, corresponding to the component outputs:
            sum_output_ref = add_multiply_task.outputs["sum"]

            # These task output references can be passed to other component functions, constructing a computation graph:
            task2 = add_multiply_op(sum_output_ref, 5)

        Bigger data should be read from files and written to files.
        Use the :py:class:`kfp.components.InputPath` parameter annotation to tell the system that the function wants to consume the corresponding input data as a file. The system will download the data, write it to a local file and then pass the **path** of that file to the function.
        Use the :py:class:`kfp.components.OutputPath` parameter annotation to tell the system that the function wants to produce the corresponding output data as a file. The system will prepare and pass the **path** of a file where the function should write the output data. After the function exits, the system will upload the data to the storage system so that it can be passed to downstream components.

        You can specify the type of the consumed/produced data by specifying the type argument to :py:class:`kfp.components.InputPath` and :py:class:`kfp.components.OutputPath`. The type can be a python type or an arbitrary type name string. :code:`OutputPath('CatBoostModel')` means that the function states that the data it has written to a file has type :code:`CatBoostModel`. :code:`InputPath('CatBoostModel')` means that the function states that it expect the data it reads from a file to have type 'CatBoostModel'. When the pipeline author connects inputs to outputs the system checks whether the types match.
        Every kind of data can be consumed as a file input. Conversely, bigger data should not be consumed by value as all value inputs pass through the command line.

        Example of a component function declaring file input and output::

            def catboost_train_classifier(
                training_data_path: InputPath(
                    "CSV"
                ),  # Path to input data file of type "CSV"
                trained_model_path: OutputPath(
                    "CatBoostModel"
                ),  # Path to output data file of type "CatBoostModel"
                number_of_trees: int = 100,  # Small output of type "Integer"
            ) -> NamedTuple(
                "Outputs",
                [
                    ("Accuracy", float),  # Small output of type "Float"
                    ("Precision", float),  # Small output of type "Float"
                    ("JobUri", "URI"),  # Small output of type "URI"
                ],
            ):
                """Train CatBoost classification model"""
                ...

                return (accuracy, precision, recall)
    '''
    core_packages = ["wandb", "kfp"]

    if not packages_to_install:
        packages_to_install = core_packages
    else:
        packages_to_install += core_packages

    component_spec = _func_to_component_spec(
        func=func,
        extra_code=wandb_logging_extras,
        base_image=base_image,
        packages_to_install=packages_to_install,
    )
    if annotations:
        component_spec.metadata = structures.MetadataSpec(
            annotations=annotations,
        )

    if output_component_file:
        component_spec.save(output_component_file)

    return _create_task_factory_from_component_spec(component_spec)


def strip_type_hints(source_code: str) -> str:
    """Strip type hints from source code.

    This function is modified from KFP.  The original source is below:
    https://github.com/kubeflow/pipelines/blob/b6406b02f45cdb195c7b99e2f6d22bf85b12268b/sdk/python/kfp/components/_python_op.py#L237-L248.
    """
    # For wandb, do not strip type hints

    #     try:
    #         return _strip_type_hints_using_lib2to3(source_code)
    #     except Exception as ex:
    #         print('Error when stripping type annotations: ' + str(ex))

    #     try:
    #         return _strip_type_hints_using_strip_hints(source_code)
    #     except Exception as ex:
    #         print('Error when stripping type annotations: ' + str(ex))

    return source_code
