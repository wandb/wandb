from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def binding_evidence(cuda: Any, env: Mapping[str, str]) -> dict[str, Any]:
    if not cuda.is_initialized():
        return {"status": "unavailable", "reason": "cuda_not_initialized"}
    index = cuda.current_device()
    props = cuda.get_device_properties(index)
    uuid = getattr(props, "uuid", None)
    if uuid:
        value = str(uuid).strip()
        if not value.startswith("GPU-"):
            value = "GPU-" + value
        return {
            "status": "available",
            "gpu_uuid": value,
            "cuda_index": index,
            "source": "cuda_runtime",
        }
    visible = env.get("CUDA_VISIBLE_DEVICES", "").split(",")
    if 0 <= index < len(visible) and visible[index].strip().startswith("GPU-"):
        import pynvml

        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByUUID(visible[index].strip())
            value = pynvml.nvmlDeviceGetUUID(handle)
            if isinstance(value, bytes):
                value = value.decode("ascii")
            return {
                "status": "available",
                "gpu_uuid": value,
                "cuda_index": index,
                "source": "cuda_visible_devices_uuid",
            }
        finally:
            pynvml.nvmlShutdown()
    return {"status": "partial", "reason": "unproven_mapping", "cuda_index": index}
