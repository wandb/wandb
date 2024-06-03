import logging
import shlex
from typing import Any, List, Optional

import wandb

from .._project_spec import LaunchProject
from ..errors import LaunchError
from ..utils import (
    LOG_PREFIX,
    MAX_ENV_LENGTHS,
    PROJECT_SYNCHRONOUS,
    sanitize_wandb_api_key,
    validate_wandb_python_deps,
)
from .abstract import AbstractRun, AbstractRunner
from .local_container import _run_entry_point

_logger = logging.getLogger(__name__)


class LocalProcessRunner(AbstractRunner):
    """Runner class, uses a project to create a LocallySubmittedRun.

    LocalProcessRunner is very similar to a LocalContainerRunner, except it does not
    run the command inside a docker container. Instead, it runs the
    command specified as a process directly on the bare metal machine.

    """

    async def run(  # type: ignore
        self,
        launch_project: LaunchProject,
        *args,
        **kwargs,
    ) -> Optional[AbstractRun]:
        if args is not None:
            _msg = f"{LOG_PREFIX}LocalProcessRunner.run received unused args {args}"
            _logger.warning(_msg)
        if kwargs is not None:
            _msg = f"{LOG_PREFIX}LocalProcessRunner.run received unused kwargs {kwargs}"
            _logger.warning(_msg)

        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]
        entry_point = (
            launch_project.override_entrypoint or launch_project.get_job_entry_point()
        )

        cmd: List[Any] = []

        if launch_project.project_dir is None:
            raise LaunchError("Launch LocalProcessRunner received empty project dir")

        if launch_project.job:
            assert launch_project._job_artifact is not None
            try:
                validate_wandb_python_deps(
                    "requirements.frozen.txt",
                    launch_project.project_dir,
                )
            except Exception:
                wandb.termwarn("Unable to validate python dependencies")
        env_vars = launch_project.get_env_vars_dict(
            self._api, MAX_ENV_LENGTHS[self.__class__.__name__]
        )
        for env_key, env_value in env_vars.items():
            cmd += [f"{shlex.quote(env_key)}={shlex.quote(env_value)}"]
        if entry_point is not None:
            cmd += entry_point.command
        cmd += launch_project.override_args

        command_str = " ".join(cmd).strip()
        _msg = f"{LOG_PREFIX}Launching run as a local-process with command {sanitize_wandb_api_key(command_str)}"
        wandb.termlog(_msg)
        run = _run_entry_point(command_str, launch_project.project_dir)
        if synchronous:
            await run.wait()
        return run
