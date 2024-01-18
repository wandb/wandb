from ..controller import register_controller_impl

from .local_process import local_process_controller
from .k8s import k8s_controller

register_controller_impl('local-process', local_process_controller)
register_controller_impl('k8s', k8s_controller)

#__all__ = ['local_process_controller', 'k8s_controller']