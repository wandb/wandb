import inspect
from typing import Any, Dict, Sequence


def chunkify(input_list, chunk_size):
    chunk_size = max(1, chunk_size)
    return [
        input_list[i : i + chunk_size] for i in range(0, len(input_list), chunk_size)
    ]


def get_updated_kwargs(
    pipeline: Any, args: Sequence[Any], kwargs: Dict[str, Any]
) -> Dict[str, Any]:
    pipeline_call_parameters = list(
        inspect.signature(pipeline.__call__).parameters.items()
    )
    for idx, arg in enumerate(args):
        kwargs[pipeline_call_parameters[idx][0]] = arg
    for pipeline_parameter in pipeline_call_parameters:
        if pipeline_parameter[0] not in kwargs:
            kwargs[pipeline_parameter[0]] = pipeline_parameter[1].default
    if "generator" in kwargs:
        generator = kwargs.pop("generator", None)
        kwargs["seed"] = (
            generator.get_state().to("cpu").tolist()[0]
            if generator is not None
            else None
        )
    return kwargs
