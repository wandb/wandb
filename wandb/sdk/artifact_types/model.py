from enum import Enum
from typing import Optional
import wandb
from wandb.apis.public import Artifact as PublicArtifact
import wandb.data_types as data_types
# from ..interface.artifacts import ArtifactEntry


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
            model_name = "model-{}".format(wandb.util.generate_id(4))

        self._model_name = model_name
        self._scope = scope

    def new(self, artifact_kwargs: dict = {}, run_kwargs: dict = {}):
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

    def log(self, obj, artifact_kwargs: dict = {}):
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
            return wandb.Api().artifact_type(
                name="{}.{}:{}".format(run_name, self._model_name)
            )
        elif self._scope == ModelScope.PROJECT:
            return wandb.Api().artifact_type(name="{}:{}".format(self._model_name))
        else:
            raise RuntimeError("Invalid scope")

    def make_reference_version(self, artifact:PublicArtifact, artifact_kwargs: dict = {}):
        version = self.new(artifact_kwargs=artifact_kwargs)
        for key in artifact.manifest.entries:
            version.add_reference(artifact[key], key)
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
            with self.new_file("{}/model.pt".format()) as f:
                maybe_torch.save(obj, f.name())
            with self.new_file("{}/state.json".format()) as f:
                maybe_torch.save(obj.state_dict(), f.name())
            with self.new_file("{}/wb_meta.json".format()) as f:
                f.write(
                    {
                        "_type": "torch.nn.Module",
                        "version": 0,
                        "content": {"model": "model.pt", "state": "state.json"},
                    }
                )
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
