import os

import wandb

from .data_types._dtypes import TypeRegistry
from .wandb_run import Run


class Job:
    def __init__(self, run: Run):
        self._run = run

    @classmethod
    def _has_job_reqs(run: Run) -> bool:
        """Returns True if the run has job requirements."""
        has_repo = run._remote_url is not None and run._last_commit is not None
        has_main_file = wandb.util.has_main_file(run._settings.program)
        has_code_artifact = bool(run._code_artifact)
        return ((has_repo or has_code_artifact) and has_main_file) or os.environ.get(
            "WANDB_DOCKER"
        ) is not None

    def _create_job(self, run: Run) -> None:
        artifact = None
        has_repo = (
            self._run._remote_url is not None and self._run._last_commit is not None
        )
        input_types = TypeRegistry.type_of(self._run.config.as_dict()).to_json()
        output_types = TypeRegistry.type_of(self._run.summary._as_dict()).to_json()

        import pkg_resources

        installed_packages_list = sorted(
            [f"{d.key}=={d.version}" for d in iter(pkg_resources.working_set)]
        )
        if has_repo:
            artifact = self._create_repo_job(
                input_types, output_types, installed_packages_list
            )
        elif self._run._code_artifact:
            artifact = self._create_artifact_job(
                input_types, output_types, installed_packages_list
            )
        elif os.environ.get("WANDB_DOCKER"):
            artifact = self._create_container_job(input_types, output_types)

        if artifact:
            artifact.wait()
            metadata = artifact.metadata
            if not metadata:
                artifact.metadata["config_defaults"] = self.config.as_dict()
                artifact.save()

    def _create_repo_job(self):
        pass

    def _create_artifact_job(self):
        pass

    def _create_container_job(self):
        pass
