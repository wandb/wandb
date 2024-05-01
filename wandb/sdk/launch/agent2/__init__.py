from .agent import LaunchAgent2
from .controllers import (
    k8s_controller,
    local_container_controller,
    local_process_controller,
    sagemaker_controller,
    vertex_controller,
)

LaunchAgent2.register_controller_impl("local-process", local_process_controller)
LaunchAgent2.register_controller_impl("local-container", local_container_controller)
LaunchAgent2.register_controller_impl("kubernetes", k8s_controller)
LaunchAgent2.register_controller_impl("vertex", vertex_controller)
LaunchAgent2.register_controller_impl("sagemaker", sagemaker_controller)

__all__ = ["LaunchAgent2"]
