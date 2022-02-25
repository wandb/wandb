import datetime
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from kubernetes import client, config
from six.moves import shlex_quote
import wandb
import wandb.docker as docker
from wandb.errors import LaunchError
from wandb.util import get_module
import yaml

from .abstract import AbstractRun, AbstractRunner, Status
from .._project_spec import LaunchProject
from ..docker import (
    generate_docker_image,
    pull_docker_image,
    validate_docker_installation,
)
from ..utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)


class KubernetesRun(AbstractRun):
    def __init__(self) -> None:
        pass

    @property
    def id(self) -> str:
        pass

    def wait(self) -> bool:
        pass

    def get_status(self) -> Status:
        pass

    def cancel(self) -> None:
        pass


class KubernetesRunner(AbstractRunner):
    def run(self, launch_project: LaunchProject) -> Optional[AbstractRun]:
        pass


