from __future__ import annotations

import os
from functools import wraps
from inspect import signature
from typing import Any, Callable

from kfp.dsl import Artifact as _KfpArtifact
from kfp.dsl.types.type_annotations import (
    InputPath,
    OutputPath,
    is_artifact_wrapped_in_Input,
    is_artifact_wrapped_in_Output,
)

import wandb
from wandb.sdk.lib import telemetry as wb_telemetry


def _is_namedtuple(x: Any) -> bool:
    """Return True if *x* is a ``NamedTuple`` instance.

    Python has no common base class for named tuples created via
    ``collections.namedtuple`` or ``typing.NamedTuple``.  The canonical
    detection pattern checks that the type is a ``tuple`` subclass whose
    ``_fields`` attribute is a tuple of strings.

    KFP uses NamedTuples for multi-output components, so we need this to
    log each output field separately.
    """
    t = type(x)
    if not issubclass(t, tuple):
        return False
    fields = getattr(t, "_fields", None)
    if not isinstance(fields, tuple):
        return False
    return all(isinstance(n, str) for n in fields)


def _is_kfp_artifact_value(value: Any) -> bool:
    """Return True if *value* is a KFP v2 artifact instance."""
    return isinstance(value, _KfpArtifact)


def _is_output_annotation(ann: Any) -> bool:
    """Return True if *ann* is a KFP ``Output[...]`` or ``OutputPath`` annotation."""
    return is_artifact_wrapped_in_Output(ann) or isinstance(ann, OutputPath)


def _is_input_annotation(ann: Any) -> bool:
    """Return True if *ann* is a KFP ``Input[...]`` or ``InputPath`` annotation."""
    return is_artifact_wrapped_in_Input(ann) or isinstance(ann, InputPath)


def _get_artifact_path(value: Any) -> str | None:
    """Return the local file path for a KFP artifact value, or ``None``."""
    if _is_kfp_artifact_value(value):
        return value.path if os.path.exists(value.path) else None
    if isinstance(value, str) and os.path.exists(value):
        return value
    return None


def _log_artifact(
    run: wandb.sdk.wandb_run.Run,
    name: str,
    value: Any,
    *,
    use: bool = False,
) -> bool:
    """Log or use a single artifact. Returns ``True`` on success."""
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


def _classify_annotations(
    func: Callable,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Split a function's annotations into scalar and artifact categories.

    Returns:
        A 4-tuple of ``(input_scalars, input_artifacts, output_scalars,
        output_artifacts)`` where each element is a ``{name: annotation}``
        mapping.
    """
    scalars_in: dict[str, Any] = {}
    artifacts_in: dict[str, Any] = {}
    scalars_out: dict[str, Any] = {}
    artifacts_out: dict[str, Any] = {}
    for name, ann in func.__annotations__.items():
        if name == "return":
            scalars_out[name] = ann
        elif _is_output_annotation(ann):
            artifacts_out[name] = ann
        elif _is_input_annotation(ann):
            artifacts_in[name] = ann
        else:
            scalars_in[name] = ann
    return scalars_in, artifacts_in, scalars_out, artifacts_out


def _log_inputs(
    run: wandb.sdk.wandb_run.Run,
    bound_args: dict[str, Any],
    input_scalars: dict[str, Any],
    input_artifacts: dict[str, Any],
) -> None:
    """Log scalar configs and input artifacts for a component invocation."""
    for name in input_scalars:
        if name in bound_args:
            value = bound_args[name]
            run.config[name] = value
            wandb.termlog(f"Setting config: {name} to {value}")

    for name in input_artifacts:
        if name in bound_args:
            try:
                _log_artifact(run, name, bound_args[name], use=True)
            except Exception as e:
                wandb.termwarn(f"Failed to log input artifact '{name}': {e}")


def _log_outputs(
    run: wandb.sdk.wandb_run.Run,
    func_name: str,
    result: Any,
    bound_args: dict[str, Any],
    output_artifacts: dict[str, Any],
) -> None:
    """Log scalar results and output artifacts for a component invocation."""
    if result is not None and not run._is_finished:
        if _is_namedtuple(result):
            for k, v in zip(result._fields, result):
                run.log({f"{func_name}.{k}": v})
        else:
            run.log({func_name: result})

    for name in output_artifacts:
        if name in bound_args:
            try:
                _log_artifact(run, name, bound_args[name], use=False)
            except Exception as e:
                wandb.termwarn(f"Failed to log output artifact '{name}': {e}")


def wandb_log(
    func: Callable | None = None,
) -> Callable:
    """Wrap a KFP v2 component function and log to W&B.

    Compatible with ``kfp>=2.0.0``.  Automatically logs input parameters
    to ``wandb.config`` and output scalars via ``wandb.log``.  Artifacts
    annotated with KFP's ``Input`` / ``Output`` types are logged as W&B
    Artifacts.

    Usage::

        from kfp import dsl
        from wandb.integration.kfp import wandb_log

        @dsl.component
        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b
    """

    def decorator(func: Callable) -> Callable:
        input_scalars, input_artifacts, _, output_artifacts = (
            _classify_annotations(func)
        )
        func_sig = signature(func)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = func_sig.bind(*args, **kwargs)
            bound.apply_defaults()

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

                _log_inputs(run, bound.arguments, input_scalars, input_artifacts)

                with wb_telemetry.context(run=run) as tel:
                    tel.feature.kfp_wandb_log = True

                result = func(*bound.args, **bound.kwargs)

                _log_outputs(
                    run, func.__name__, result, bound.arguments, output_artifacts
                )

            return result

        wrapper._wandb_logged = True
        wrapper.__signature__ = func_sig
        return wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)
