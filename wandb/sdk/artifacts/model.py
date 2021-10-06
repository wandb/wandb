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

class CustomLocalArtifactCollectionABC(object):
    def __init__(self, name: str, type_name:str):
        self._name = name
        self._type_name = type_name

    def load(self, alias: str = "latest"):
        return wandb.Api().artifact(name="{}:{}".format(self._name, alias))

    def versions(self):
        return wandb.Api().artifact_versions(name="{}".format(self._name), type_name=self._type_name)

    def new_version_from_copy(self, artifact:PublicArtifact, artifact_kwargs: dict = {}):
        version = self.new_version(artifact_kwargs=artifact_kwargs)
        for key in artifact.manifest.entries:
            version.add_reference(artifact.get_path(key).ref_url(), key)
        version.metadata = artifact.metadata
        version.save()

class RunModelLocalArtifactType:
    def new_artifact(self, collection_kwargs: dict = {}):
        collection_kwargs = collection_kwargs.copy()
        collection_kwargs["type_name"] = "wb.run_model"
        return ModelLocalArtifactCollection(**collection_kwargs)

class ProjectModelLocalArtifactType:
    def new_artifact(self, collection_kwargs: dict = {}):
        collection_kwargs = collection_kwargs.copy()
        collection_kwargs["type_name"] = "wb.project_model"
        return ModelLocalArtifactCollection(**collection_kwargs)

class ModelLocalArtifactCollection(CustomLocalArtifactCollectionABC):
    def new_version(self, artifact_kwargs: dict = {}):
        artifact_kwargs = artifact_kwargs.copy()
        artifact_kwargs["name"] = self._name
        artifact_kwargs["type"] = self._type_name
        return ModelLocalArtifactVersion(**artifact_kwargs)

    def new_version_from_obj(self, obj, path:str = "model", artifact_kwargs: dict = {}):
        version = self.new_version(artifact_kwargs=artifact_kwargs)
        version.add(obj, path)
        version.save()
        return version

class ModelLocalArtifactVersion(wandb.Artifact):
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
