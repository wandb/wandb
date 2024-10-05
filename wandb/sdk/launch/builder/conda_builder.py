"""Conda builder implementation."""

import hashlib
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

import wandb
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.lib.filenames import FROZEN_CONDA_FNAME

from .._project_spec import EntryPoint, LaunchProject
from ..agent.job_status_tracker import JobAndRunStatusTracker
from .build import list_conda_envs, validate_conda_installation

_logger = logging.getLogger(__name__)


class CondaBuilder(AbstractBuilder):
    """Conda builder."""

    type = "conda"

    def __init__(
        self,
        builder_config: Dict[str, Any],
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
        verify: bool = True,
    ) -> None:
        """Initialize a CondaBuilder."""
        self.environment = environment
        self.registry = registry
        self.builder_config = builder_config
        self.verify = verify

    @classmethod
    def from_config(
        cls,
        config: dict,
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
        verify: bool = True,
    ) -> "AbstractBuilder":
        """Create a conda builder from a config."""
        return cls(config, environment, registry, verify)

    async def verify(self) -> None:
        """Verify the builder."""
        if not self.verify:
            return
        return validate_conda_installation()

    def _create_conda_env(self, launch_project: LaunchProject) -> None:
        """Create a conda environment."""
        frozen_conda_path = Path(launch_project.project_dir) / FROZEN_CONDA_FNAME
        lines = []
        dev_mode = os.getenv("WANDB_EDITABLE_PATH") is not None
        python_version = None
        # Readlines from conda file, find python version and check if we have
        # wandb installed in editable mode
        with open(frozen_conda_path) as f:
            for line in f:
                if "python=" in line:
                    python_version = line.split("=")[1].strip()
                if "wandb" in line:
                    if "dev" in line:
                        dev_mode = True
                        continue
                    else:
                        lines.append(line)
                else:
                    lines.append(line)
        # TODO (slurm): support modifying the python version?
        if python_version != launch_project.python_version:
            _logger.warning(
                f"Python version mismatch: {python_version} != {launch_project.python_version}"
            )
        with open(frozen_conda_path, "w") as f:
            f.writelines(lines)
        # TODO (slurm): maybe throw this into the build_log
        venv_digest = hashlib.md5("".join(lines).encode("utf-8")).hexdigest()
        env_dir = Path(
            launch_project.slurm_env_dir.replace(launch_project.slurm_env_name, "")
        )
        existing_env = None
        if (env_dir / f"{venv_digest}.txt").exists():
            with open(env_dir / f"{venv_digest}.txt") as f:
                existing_env = f.read()
            if not os.path.exists(existing_env):
                existing_env = None
        start = time.time()
        if existing_env:
            _logger.info(f"Found conda env {existing_env}, cloning and updating")
            wandb.termlog(f"Found conda env {existing_env}, cloning and updating")
            subprocess.check_call(
                [
                    "conda",
                    "create",
                    "--clone",
                    existing_env,
                    "-p",
                    launch_project.slurm_env_dir,
                ]
            )
        else:
            subprocess.check_call(
                [
                    "conda",
                    "env",
                    "create",
                    "-f",
                    str(frozen_conda_path),
                    "-p",
                    launch_project.slurm_env_dir,
                ]
            )
        with open(env_dir / f"{venv_digest}.txt", "w") as f:
            f.write(launch_project.slurm_env_dir)
        print(f"Took {time.time() - start} seconds")
        # TODO (slurm): this is for editable wandb installs during development, consider making more generic
        if dev_mode:
            _logger.info("Installing editable wandb...")
            # TODO (slurm): this assumes ~/.bashrc exists, should atleast error out if it doesn't
            # If we have CONDA_BASE set, we should use that https://github.com/GoogleCloudPlatform/scientific-computing-examples/blob/main/llama2-finetuning-slurm/files/fine-tune-slurm.sh
            subprocess.check_call(
                [
                    "bash",
                    "-c",
                    f"source ~/.bashrc && conda activate {launch_project.slurm_env_dir} && pip install -e {os.getenv('WANDB_EDITABLE_PATH', '/dev/client')}",
                ]
            )

    def _modify_entrypoint(
        self, launch_project: LaunchProject, entrypoint_path: Path
    ) -> None:
        """Modify the entrypoint to ensure our environment is activated."""
        # TODO (slurm): test that we get reasonable errors in the launch UI if we munge this
        _logger.info(f"Modifying {entrypoint_path} to activate our conda environment")
        source_lines = []
        # found = False
        # srun_index = -1
        with open(entrypoint_path) as f:
            for line in f:
                if "conda activate" in line:
                    # found = True
                    source_lines.append(
                        f"conda activate {launch_project.slurm_env_dir}\n"
                    )
                    continue
                # elif "srun" in line:
                #    srun_index = i
                source_lines.append(line)
        # TODO (slurm): test this, decide if it's a good idea, might need to source ~/.bashrc
        # if not found:
        #    _logger.warning(
        #        f"No conda environment found in {entrypoint_path}, adding one"
        #    )
        #    if srun_index == -1:
        #        raise LaunchError(f"No srun command found in {entrypoint_path}")
        #    source_lines.insert(
        #        srun_index - 1,
        #        f"conda activate {launch_project.slurm_env_dir}\n",
        #    )
        with open(entrypoint_path, "w") as f:
            f.writelines(source_lines)

    # TODO (slurm): build_image is a misnomer here, perhaps we should change this to build_env
    async def build_image(
        self,
        launch_project: LaunchProject,
        entrypoint: EntryPoint,
        job_tracker: Optional[JobAndRunStatusTracker] = None,
    ) -> str:
        """Build the environment.

        For this we raise a launch error since it can't build.
        """
        conda_env_name = launch_project.resource_args["slurm"].get("conda-env")
        if conda_env_name in list_conda_envs():
            _logger.info(
                f"Conda environment {conda_env_name} already exists, skipping creation"
            )
            wandb.termlog(f"Using existing conda environment {conda_env_name}")
            return conda_env_name
        # TODO (slurm): we might want to move the frozen env into the build context
        # launch_project.job_build_context or ""
        frozen_conda_path = Path(launch_project.project_dir) / FROZEN_CONDA_FNAME
        # TODO (slurm): add status to job_tracker for failures?
        if (
            frozen_conda_path.exists()
            and not Path(launch_project.slurm_env_dir).exists()
        ):
            _logger.info(
                f"Creating conda environment in {launch_project.slurm_env_dir}"
            )
            wandb.termlog(
                f"Creating conda environment in {launch_project.slurm_env_dir}"
            )
            self._create_conda_env(launch_project)
        elif not frozen_conda_path.exists():
            wandb.termwarn(
                f"No frozen conda environment found in {launch_project.project_dir}"
            )
            # TODO: should we error here?  Just tell the user we'll use the current env?
        else:
            wandb.termlog(
                f"Conda environment {launch_project.slurm_env_dir} already exists, skipping creation"
            )

        # TODO: figure out a better way to find the actual file
        likely_sh = "slurm.sh"
        for c in entrypoint.command:
            if ".sh" in c:
                likely_sh = c
        entrypoint_path = (
            Path(launch_project.project_dir, launch_project.job_build_context or "")
            / likely_sh
        )
        if not entrypoint_path.exists():
            raise LaunchError(f"No entrypoint found for {likely_sh}")
        else:
            self._modify_entrypoint(launch_project, entrypoint_path)
        # TODO: think more about me...
        return launch_project.slurm_env_dir
