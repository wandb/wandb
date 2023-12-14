import inspect
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

import wandb
from wandb.util import get_module

if TYPE_CHECKING:
    np_array = get_module("numpy.array")


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
    if "ip_adapter_image" in kwargs:
        if kwargs["ip_adapter_image"] is not None:
            wandb.log({"IP-Adapter-Image": wandb.Image(kwargs["ip_adapter_image"])})
    return kwargs


def postprocess_pils_to_np(image: List) -> "np_array":
    np = get_module(
        "numpy",
        required="Please ensure NumPy is installed. You can run `pip install numpy` to install it.",
    )
    return np.stack(
        [np.transpose(np.array(img).astype("uint8"), axes=(2, 0, 1)) for img in image],
        axis=0,
    )


def postprocess_np_arrays_for_video(
    images: List["np_array"], normalize: Optional[bool] = False
) -> "np_array":
    np = get_module(
        "numpy",
        required="Please ensure NumPy is installed. You can run `pip install numpy` to install it.",
    )
    images = [(img * 255).astype("uint8") for img in images] if normalize else images
    return np.transpose(np.stack((images), axis=0), axes=(0, 3, 1, 2))
