def wandb_log(  # noqa: C901
    func=None,
    # /,  # py38 only
    log_component_file=True,
):
    """Wrap a kfp v1 python functional component and log to W&B.

    Requires kfp<2.0.0. For kfp>=2.0.0, use wandb_log_v2.
    """
    import json
    import os
    from functools import wraps
    from inspect import Parameter, signature

    from kfp import components
    from kfp.components import (
        InputArtifact,
        InputBinaryFile,
        InputPath,
        InputTextFile,
        OutputArtifact,
        OutputBinaryFile,
        OutputPath,
        OutputTextFile,
    )

    import wandb
    from wandb.sdk.lib import telemetry as wb_telemetry

    output_types = (OutputArtifact, OutputBinaryFile, OutputPath, OutputTextFile)
    input_types = (InputArtifact, InputBinaryFile, InputPath, InputTextFile)

    def isinstance_namedtuple(x):
        t = type(x)
        b = t.__bases__
        if len(b) != 1 or b[0] is not tuple:
            return False
        f = getattr(t, "_fields", None)
        if not isinstance(f, tuple):
            return False
        return all(isinstance(n, str) for n in f)

    def get_iframe_html(run):
        return f'<iframe src="{run.url}?kfp=true" style="border:none;width:100%;height:100%;min-width:900px;min-height:600px;"></iframe>'

    def get_link_back_to_kubeflow():
        wandb_kubeflow_url = os.getenv("WANDB_KUBEFLOW_URL")
        return f"{wandb_kubeflow_url}/#/runs/details/{{workflow.uid}}"

    def log_input_scalar(name, data, run=None):
        run.config[name] = data
        wandb.termlog(f"Setting config: {name} to {data}")

    def log_input_artifact(name, data, type, run=None):
        artifact = wandb.Artifact(name, type=type)
        artifact.add_file(data)
        run.use_artifact(artifact)
        wandb.termlog(f"Using artifact: {name}")

    def log_output_scalar(name, data, run=None):
        if isinstance_namedtuple(data):
            for k, v in zip(data._fields, data):
                run.log({f"{func.__name__}.{k}": v})
        else:
            run.log({name: data})

    def log_output_artifact(name, data, type, run=None):
        artifact = wandb.Artifact(name, type=type)
        artifact.add_file(data)
        run.log_artifact(artifact)
        wandb.termlog(f"Logging artifact: {name}")

    def _log_component_file(func, run=None):
        name = func.__name__
        output_component_file = f"{name}.yml"
        components._python_op.func_to_component_file(func, output_component_file)
        artifact = wandb.Artifact(name, type="kubeflow_component_file")
        artifact.add_file(output_component_file)
        run.log_artifact(artifact)
        wandb.termlog(f"Logging component file: {output_component_file}")

    # Add `mlpipeline_ui_metadata_path` to signature to show W&B run in "ML Visualizations tab"
    sig = signature(func)
    no_default = []
    has_default = []

    for param in sig.parameters.values():
        if param.default is param.empty:
            no_default.append(param)
        else:
            has_default.append(param)

    new_params = tuple(
        (
            *no_default,
            Parameter(
                "mlpipeline_ui_metadata_path",
                annotation=OutputPath(),
                kind=Parameter.POSITIONAL_OR_KEYWORD,
            ),
            *has_default,
        )
    )
    new_sig = sig.replace(parameters=new_params)
    new_anns = {param.name: param.annotation for param in new_params}
    if "return" in func.__annotations__:
        new_anns["return"] = func.__annotations__["return"]

    def decorator(func):
        input_scalars = {}
        input_artifacts = {}
        output_scalars = {}
        output_artifacts = {}

        for name, ann in func.__annotations__.items():
            if name == "return":
                output_scalars[name] = ann
            elif isinstance(ann, output_types):
                output_artifacts[name] = ann
            elif isinstance(ann, input_types):
                input_artifacts[name] = ann
            else:
                input_scalars[name] = ann

        @wraps(func)
        def wrapper(*args, **kwargs):
            bound = new_sig.bind(*args, **kwargs)
            bound.apply_defaults()

            mlpipeline_ui_metadata_path = bound.arguments["mlpipeline_ui_metadata_path"]
            del bound.arguments["mlpipeline_ui_metadata_path"]

            with wandb.init(
                job_type=func.__name__,
                group="{{workflow.annotations.pipelines.kubeflow.org/run_name}}",
            ) as run:
                # Link back to the kfp UI
                kubeflow_url = get_link_back_to_kubeflow()
                run.notes = kubeflow_url
                run.config["LINK_TO_KUBEFLOW_RUN"] = kubeflow_url

                iframe_html = get_iframe_html(run)
                metadata = {
                    "outputs": [
                        {
                            "type": "markdown",
                            "storage": "inline",
                            "source": iframe_html,
                        }
                    ]
                }

                with open(mlpipeline_ui_metadata_path, "w") as metadata_file:
                    json.dump(metadata, metadata_file)

                if log_component_file:
                    _log_component_file(func, run=run)

                for name, _ in input_scalars.items():
                    log_input_scalar(name, kwargs[name], run)

                for name, ann in input_artifacts.items():
                    log_input_artifact(name, kwargs[name], ann.type, run)

                with wb_telemetry.context(run=run) as tel:
                    tel.feature.kfp_wandb_log = True

                result = func(*bound.args, **bound.kwargs)

                for name, _ in output_scalars.items():
                    log_output_scalar(name, result, run)

                for name, ann in output_artifacts.items():
                    log_output_artifact(name, kwargs[name], ann.type, run)

            return result

        wrapper.__signature__ = new_sig
        wrapper.__annotations__ = new_anns
        return wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)


def wandb_log_v2(  # noqa: C901
    func=None,
):
    """Wrap a kfp v2 component function and log to W&B.

    Compatible with kfp>=2.0.0. Automatically logs input parameters to
    wandb.config and output scalars via wandb.log. Artifacts annotated
    with kfp's Input/Output types are logged as W&B Artifacts.

    Usage::

        from kfp import dsl
        from wandb.integration.kfp import wandb_log

        @dsl.component
        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b
    """
    import os
    from functools import wraps
    from inspect import signature

    import wandb
    from wandb.sdk.lib import telemetry as wb_telemetry

    def isinstance_namedtuple(x):
        t = type(x)
        b = t.__bases__
        if len(b) != 1 or b[0] is not tuple:
            return False
        f = getattr(t, "_fields", None)
        if not isinstance(f, tuple):
            return False
        return all(isinstance(n, str) for n in f)

    def _is_kfp_artifact_value(value):
        """Check if a runtime value is a kfp v2 artifact object."""
        return hasattr(value, "path") and hasattr(value, "uri")

    def _is_output_annotation(ann):
        try:
            from kfp.dsl.types.type_annotations import OutputPath
            from kfp.dsl.types.type_annotations import is_artifact_wrapped_in_Output

            return is_artifact_wrapped_in_Output(ann) or isinstance(ann, OutputPath)
        except Exception:
            ann_str = str(ann)
            return "Output" in ann_str

    def _is_input_annotation(ann):
        try:
            from kfp.dsl.types.type_annotations import InputPath
            from kfp.dsl.types.type_annotations import is_artifact_wrapped_in_Input

            return is_artifact_wrapped_in_Input(ann) or isinstance(ann, InputPath)
        except Exception:
            ann_str = str(ann)
            return "Input" in ann_str and "Output" not in ann_str

    def decorator(func):
        input_scalars = {}
        input_artifacts = {}
        output_scalars = {}
        output_artifacts = {}

        for name, ann in func.__annotations__.items():
            if name == "return":
                output_scalars[name] = ann
            elif _is_output_annotation(ann):
                output_artifacts[name] = ann
            elif _is_input_annotation(ann):
                input_artifacts[name] = ann
            else:
                input_scalars[name] = ann

        func_sig = signature(func)

        @wraps(func)
        def wrapper(*args, **kwargs):
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

                for name in input_scalars:
                    if name in bound.arguments:
                        value = bound.arguments[name]
                        run.config[name] = value
                        wandb.termlog(f"Setting config: {name} to {value}")

                for name in input_artifacts:
                    if name in bound.arguments:
                        value = bound.arguments[name]
                        try:
                            if _is_kfp_artifact_value(value):
                                if os.path.exists(value.path):
                                    artifact = wandb.Artifact(
                                        name, type="kfp_artifact"
                                    )
                                    artifact.add_file(value.path)
                                    run.use_artifact(artifact)
                                    wandb.termlog(f"Using artifact: {name}")
                            elif isinstance(value, str) and os.path.exists(value):
                                artifact = wandb.Artifact(name, type="kfp_artifact")
                                artifact.add_file(value)
                                run.use_artifact(artifact)
                                wandb.termlog(f"Using artifact: {name}")
                        except Exception as e:
                            wandb.termwarn(
                                f"Failed to log input artifact '{name}': {e}"
                            )

                with wb_telemetry.context(run=run) as tel:
                    tel.feature.kfp_wandb_log = True

                result = func(*bound.args, **bound.kwargs)

                if result is not None:
                    if isinstance_namedtuple(result):
                        for k, v in zip(result._fields, result):
                            run.log({f"{func.__name__}.{k}": v})
                    else:
                        run.log({func.__name__: result})

                for name in output_artifacts:
                    if name in bound.arguments:
                        value = bound.arguments[name]
                        try:
                            if _is_kfp_artifact_value(value):
                                if os.path.exists(value.path):
                                    artifact = wandb.Artifact(
                                        name, type="kfp_artifact"
                                    )
                                    artifact.add_file(value.path)
                                    run.log_artifact(artifact)
                                    wandb.termlog(f"Logging artifact: {name}")
                            elif isinstance(value, str) and os.path.exists(value):
                                artifact = wandb.Artifact(name, type="kfp_artifact")
                                artifact.add_file(value)
                                run.log_artifact(artifact)
                                wandb.termlog(f"Logging artifact: {name}")
                        except Exception as e:
                            wandb.termwarn(
                                f"Failed to log output artifact '{name}': {e}"
                            )

            return result

        wrapper._wandb_logged = True
        wrapper.__signature__ = func_sig
        return wrapper

    if func is None:
        return decorator
    else:
        return decorator(func)
