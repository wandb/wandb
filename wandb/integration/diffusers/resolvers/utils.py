import inspect
from typing import Any, Dict, List, Optional, Sequence

from wandb.util import get_module

np = get_module("numpy")


def chunkify(input_list, chunk_size) -> List:
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


def postprocess_pils_to_np(image: List) -> np.array:
    return np.stack(
        [np.transpose(np.array(img).astype("uint8"), axes=(2, 0, 1)) for img in image],
        axis=0,
    )


def postprocess_np_arrays_for_video(
    images: List[np.array], normalize: Optional[bool] = False
):
    images = [(img * 255).astype("uint8") for img in images] if normalize else images
    return np.transpose(np.stack((images), axis=0), axes=(0, 3, 1, 2))
