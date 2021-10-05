import os
from enum import Enum
import json
from typing import Optional
import wandb
from wandb.apis.public import Artifact as PublicArtifact
import wandb.data_types as data_types
# from ..interface.artifacts import ArtifactEntry
from wandb.compat import tempfile as compat_tempfile

TMP_DIR = compat_tempfile.TemporaryDirectory("wandb-model-management")

class ModelScope(Enum):
    """
    Scope of the model.
    """

    RUN = "run"
    PROJECT = "project"
    # ORG = "org"


class Model:
    def __init__(
        self, model_name: Optional[str] = None, scope: ModelScope = ModelScope.RUN
    ):
        if scope == ModelScope.PROJECT and model_name is None:
            raise ValueError("Project scope requires a model name")
        elif model_name is None:
            model_name = wandb.util.generate_id(4)

        self._model_name = model_name
        self._scope = scope

    def new_version(self, artifact_kwargs: dict = {}, run_kwargs: dict = {}):
        if "name" in artifact_kwargs:
            del artifact_kwargs["name"]
        if self._scope == ModelScope.RUN:
            if not wandb.run:
                # raise RuntimeError("Cannot create a model version without a run")
                wandb.init(**run_kwargs)
            return RunModelLocalVersion(
                name="{}.{}".format(wandb.run.name, self._model_name),
                **artifact_kwargs
            )
        elif self._scope == ModelScope.PROJECT:
            return ProjectModelLocalVersion(name=self._model_name, **artifact_kwargs)
        else:
            raise RuntimeError("Invalid scope")

    def log_version(self, obj, artifact_kwargs: dict = {}):
        version = self.new(artifact_kwargs=artifact_kwargs)
        version.add(obj, "model")
        version.save()

    def load(self, alias: str = "latest", run_name: Optional[str] = None):
        if self._scope == ModelScope.RUN:
            if run_name is None:
                raise ValueError("Run scope requires a run name")
            return wandb.Api().artifact(
                name="{}.{}:{}".format(run_name, self._model_name, alias)
            )
        elif self._scope == ModelScope.PROJECT:
            return wandb.Api().artifact(name="{}:{}".format(self._model_name, alias))
        else:
            raise RuntimeError("Invalid scope")

    def versions(self, run_name: Optional[str] = None):
        if self._scope == ModelScope.RUN:
            if run_name is None:
                raise ValueError("Run scope requires a run name")
            return wandb.Api().artifact_versions(
                name="{}.{}".format(run_name, self._model_name), type_name="wb.run_model"
            )
        elif self._scope == ModelScope.PROJECT:
            return wandb.Api().artifact_versions(name="{}".format(self._model_name), type_name="wb.project_model")
        else:
            raise RuntimeError("Invalid scope")

    def reference_version(self, artifact:PublicArtifact, artifact_kwargs: dict = {}):
        version = self.new(artifact_kwargs=artifact_kwargs)
        for key in artifact.manifest.entries:
            version.add_reference(artifact[key].ref_url(), key)
        version.metadata = artifact.metadata
        version.save()


class CustomLocalArtifactVersion(wandb.Artifact):
    def __init__(
        self,
        name: str,
        type: str = "",
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        incremental: Optional[bool] = None,
    ):
        super().__init__(
            name=name,
            type=self._make_type(),
            description=description,
            metadata=metadata,
            incremental=incremental,
        )

    
    def _make_type(self):
        return "{}.{}".format(self._domain(), self._type_name())

    
    def _domain(self):
        raise NotImplementedError()

    
    def _type_name(self):
        raise NotImplementedError()


class ModelLocalVersion(CustomLocalArtifactVersion):
    def add(self, obj: data_types.WBValue, name: str):
        maybe_torch = wandb.util.get_module("torch")

        if maybe_torch and isinstance(obj, maybe_torch.nn.Module):
            local_folder_path = os.path.join(TMP_DIR.name, name)
            target_folder_path = name
            if not os.path.exists(local_folder_path):
                os.makedirs(local_folder_path)
            
            local_model_path = os.path.join(local_folder_path, "model.pt")
            target_model_path = os.path.join(target_folder_path, "model.pt")
            maybe_torch.save(obj, local_model_path)
            self.add_file(local_model_path, target_model_path)

            local_state_path = os.path.join(local_folder_path, "state.json")
            target_state_path = os.path.join(target_folder_path, "state.json")
            maybe_torch.save(obj.state_dict(), local_state_path)
            self.add_file(local_state_path, target_state_path)

            local_meta_path = os.path.join(local_folder_path, "meta.json")
            target_meta_path = os.path.join(target_folder_path, "meta.json")
            with open(local_meta_path, mode="w") as f:
                json.dump({
                        "_type": "torch.nn.Module",
                        "module_version": maybe_torch.version.__version__,
                        "wandb_version": wandb.__version__,
                        "content": {"model": "model.pt", "state": "state.json"},
                    }, f)
            self.add_file(local_meta_path, target_meta_path)
        else:
            return super().add(obj, name)


class RunModelLocalVersion(ModelLocalVersion):
    
    def _domain(self):
        return "wb"
    
    def _type_name(self):
        return "run_model"


class ProjectModelLocalVersion(ModelLocalVersion):
    
    def _domain(self):
        return "wb"
    
    def _type_name(self):
        return "project_model"

__all__ = [
    "Model"
]