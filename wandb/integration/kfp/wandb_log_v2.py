from __future__ import annotations

import os
from functools import wraps
from inspect import signature
from typing import Any, Callable

import kfp.dsl
from kfp.dsl.types.type_annotations import (
    InputPath,
    OutputPath,
    is_artifact_wrapped_in_Input,
    is_artifact_wrapped_in_Output,
)

import wandb
from wandb.sdk.lib import telemetry as wb_telemetry


def _is_namedtuple(x: Any) -> bool:
    """Return True if ``x`` is an instance of a NamedTuple.

    Python does not provide a common base class for named tuples created
    via ``collections.namedtuple`` or ``typing.NamedTuple``, so there is
    no way to use ``isinstance``. Instead we check that the type is a
    ``tuple`` subclass whose ``_fields`` attribute is a tuple of strings,
    following the documented NamedTuple API:
    https://docs.python.org/3/library/collections.html#collections.somenamedtuple._fields

    KFP uses NamedTuples for multi-output components. The decorator sees
    the actual return value at runtime and unpacks its fields for logging.
    KFP's own executor processes type annotations separately for
    serialization, so runtime value detection is the correct approach here.

    Args:
        x: The value to check.

    Returns:
        True if ``x`` is a NamedTuple instance.
    """
    t = type(x)
    if not issubclass(t, tuple):
        return False
    fields = getattr(t, "_fields", None)
    if not isinstance(fields, tuple):
        return False
    return all(isinstance(n, str) for n in fields)


def _is_output_annotation(ann: Any) -> bool:
    """Return True if ``ann`` is a KFP Output or OutputPath annotation."""
    return is_artifact_wrapped_in_Output(ann) or isinstance(ann, OutputPath)


def _is_input_annotation(ann: Any) -> bool:
    """Return True if ``ann`` is a KFP Input or InputPath annotation."""
    return is_artifact_wrapped_in_Input(ann) or isinstance(ann, InputPath)


def _get_artifact_path(value: Any) -> str | None:
    """Return the local file path for a KFP artifact value, or None.

    Args:
        value: A KFP artifact instance or a string file path.

    Returns:
        The local path if the artifact/file exists on disk, otherwise None.
    """
    if isinstance(value, kfp.dsl.Artifact):
        return value.path if os.path.exists(value.path) else None
    if isinstance(value, str) and os.path.exists(value):
        return value
    return None


def _log_artifact(
    run: wandb.Run,
    name: str,
    value: Any,
    *,
    use: bool = False,
) -> bool:
    """Log or use a single artifact.

    Args:
        run: The active W&B run.
        name: Artifact name.
        value: A KFP artifact or string path.
        use: If True, call ``run.use_artifact`` (for inputs); otherwise
            call ``run.log_artifact`` (for outputs).

    Returns:
        True on success, False if the artifact path is missing.
    """
    path = _get_artifact_path(value)
    if path is None:
        return False
    artifact = wandb.Artifact(name, type="kfp_artifact")
    artifact.add_file(path)
    if use:
        run.use_artifact(artifact)
        wandb.termlog(f"Using artifact: {name}")
    else:
        run.log_artifact(artifact)
        wandb.termlog(f"Logging artifact: {name}")
    return True


class _KfpWandbLogger:
    """Classifies a KFP component's annotations and logs I/O to W&B.

    Inspects the function's type annotations at decoration time to
    partition parameters into scalar inputs, artifact inputs, and
    artifact outputs. Only parameter names are stored (annotation
    values are not needed after classification).

    Args:
        func: The KFP component function to classify.
    """

    def __init__(self, func: Callable) -> None:
        self._scalars_in: set[str] = set()
        self._artifacts_in: set[str] = set()
        self._artifacts_out: set[str] = set()
        for name, ann in func.__annotations__.items():
            if name == "return":
                continue
            elif _is_output_annotation(ann):
                self._artifacts_out.add(name)
            elif _is_input_annotation(ann):
                self._artifacts_in.add(name)
            else:
                self._scalars_in.add(name)

    def log_inputs(self, run: wandb.Run, bound_args: dict[str, Any]) -> None:
        """Log scalar configs and input artifacts for a component invocation.

        Args:
            run: The active W&B run.
            bound_args: Bound arguments from ``inspect.Signature.bind``.
        """
        for name in self._scalars_in:
            if name in bound_args:
                value = bound_args[name]
                run.config[name] = value
                wandb.termlog(f"Setting config: {name} to {value}")

        for name in self._artifacts_in:
            if name in bound_args:
                try:
                    _log_artifact(run, name, bound_args[name], use=True)
                except Exception as e:
                    wandb.termwarn(f"Failed to log input artifact '{name}': {e}")

    def log_outputs(
        self,
        run: wandb.Run,
        func_name: str,
        result: Any,
        bound_args: dict[str, Any],
    ) -> None:
        """Log scalar results and output artifacts for a component invocation.

        Args:
            run: The active W&B run.
            func_name: The component function's name (used as log key prefix).
            result: The return value of the component function.
            bound_args: Bound arguments from ``inspect.Signature.bind``.
        """
        if result is not None and not run._is_finished:
            if _is_namedtuple(result):
                run.log({f"{func_name}.{k}": v for k, v in zip(result._fields, result)})
            else:
                run.log({func_name: result})

        for name in self._artifacts_out:
            if name in bound_args:
                try:
                    _log_artifact(run, name, bound_args[name], use=False)
                except Exception as e:
                    wandb.termwarn(f"Failed to log output artifact '{name}': {e}")


def wandb_log(
    func: Callable | None = None,
) -> Callable:
    """Wrap a KFP v2 component function and log to W&B.

    Compatible with ``kfp>=2.0.0``. Automatically logs input parameters
    to ``wandb.config`` and output scalars via ``wandb.log``. Artifacts
    annotated with KFP's ``Input`` / ``Output`` types are logged as W&B
    Artifacts.

    Example:
        ```python
        from kfp import dsl
        from wandb.integration.kfp import wandb_log


        @dsl.component
        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b
        ```
    """

    def decorator(func: Callable) -> Callable:
        logger = _KfpWandbLogger(func)
        func_sig = signature(func)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = func_sig.bind(*args, **kwargs)
            bound.apply_defaults()

            # WANDB_RUN_GROUP: standard W&B env var for grouping runs.
            # KFP_RUN_NAME: set by the KFP orchestrator at container runtime.
            # ARGO_WORKFLOW_NAME: set by Argo Workflows (KFP's execution backend).
            wandb_group = (
                os.getenv("WANDB_RUN_GROUP")
                or os.getenv("KFP_RUN_NAME")
                or os.getenv("ARGO_WORKFLOW_NAME")
            )
            with wandb.init(
                job_type=func.__name__,
                group=wandb_group,
            ) as run:
                kubeflow_url = os.getenv("WANDB_KUBEFLOW_URL")
                if kubeflow_url:
                    run.config["LINK_TO_KUBEFLOW"] = kubeflow_url

                logger.log_inputs(run, bound.arguments)

                with wb_telemetry.context(run=run) as tel:
                    tel.feature.kfp_wandb_log = True

                result = func(*bound.args, **bound.kwargs)

                logger.log_outputs(run, func.__name__, result, bound.arguments)

            return result

        # Checked by kfp_patch.py to detect decorated functions for wandb
        # package injection and decorator source serialization.
        wrapper._wandb_logged = True
        # KFP's executor calls inspect.getfullargspec() to discover component
        # parameters. Without this, the executor sees (*args, **kwargs) from
        # the wrapper instead of the real function signature.
        wrapper.__signature__ = func_sig
        return wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)
