import wandb
from pathlib import Path
from typing import Optional, Dict, Union, Any
import pickle

try:
    from kedro.io import AbstractDataSet
    from kedro.io import DataCatalog
    from kedro.pipeline.node import Node
    from kedro.framework.hooks import hook_impl
except ImportError as e:
    raise Exception(
        "Error `kedro` is not installed. This integration requires Kedro! Please run `pip install kedro`."
    ) from e

try:
    from fastcore.all import typedispatch
except ImportError as e:
    raise Exception(
        "Error `fastcore` is not installed. This integration requires fastcore! Please run `pip install fastcore`."
    ) from e


class WandbHooks:
    @hook_impl
    def before_pipeline_run(self, catalog: DataCatalog) -> None:
        self.catalog = catalog
        self.wandb_params = catalog.load("parameters")["wandb"]
        self.run = None

    @hook_impl
    def before_node_run(self, node: Node):
        init_parameters = {
            'entity': self.wandb_params.get('entity'),
            'project' : self.wandb_params.get('project'),
            'mode' : self.wandb_params.get('mode'),
            'job_type': self.wandb_params.get('job_type'),
            'dir' : self.wandb_params.get('dir'),
            'config' : self.wandb_params.get('config'),
            'reinit' : self.wandb_params.get('reinit'),
            'tags' : self.wandb_params.get('tags'),
            'group' : self.wandb_params.get('group'),
            'name' : self.wandb_params.get('name'),
            'notes' : self.wandb_params.get('notes'),
            'magic' : self.wandb_params.get('magic'),
            'config_exclude_keys' : self.wandb_params.get('config_exclude_keys'),
            'config_include_keys' : self.wandb_params.get('config_include_keys'),
            'anonymous' : self.wandb_params.get('anonymous'),
            'allow_val_change' : self.wandb_params.get('allow_val_change'),
            'resume' : self.wandb_params.get('resume'),
            'force' : self.wandb_params.get('force'),
            'tensorboard' : self.wandb_params.get('tensorboard'),
            'monitor_gym' : self.wandb_params.get('monitor_gym'),
            'save_code' : self.wandb_params.get('save_code'),
            'id' : self.wandb_params.get('id'),
            'settings' : self.wandb_params.get('settings')
        }

        if node.name in self.wandb_params.keys():
            # Overwrite the settings in init_parameters with node specific settings
            init_parameters.update(self.wandb_params[node.name])

        if isinstance(self.run, wandb.sdk.wandb_run.Run):
            self.run.finish()
            self.run = None

        self.run = wandb.init(**init_parameters)

        parameters = self.catalog.load("parameters")

        for parameter in parameters:
            if not parameter.startswith("wandb"):
                self.run.config[parameter] = parameters[parameter]

        for dataset in self.catalog._data_sets.values():
            # Iterating through every dataset object in the catalog to pass in wandb properties
            if isinstance(dataset, WandbArtifact):
                dataset.run = self.run
                dataset.entity = self.run.entity
                dataset.project = self.run.project

    @hook_impl
    def after_pipeline_run(self) -> None:
        self.run.finish()


# Numpy Arrays
try:
    import numpy as np

    @typedispatch
    def _serialize(filepath: Path, obj: np.ndarray) -> None:
        np.save(filepath, obj)

    def _deserialize_numpy(filepath: Path) -> np.ndarray:
        return np.load(filepath)

except ImportError:
    wandb.termwarn(
        "Warning: `numpy` is not installed. Logging arrays as Artifacts may not work."
    )

try:
    import pandas as pd

    @typedispatch
    def _serialize(filepath: Path, obj: pd.DataFrame) -> None:
        if filepath.suffix == ".csv":
            obj.to_csv(filepath)
        elif filepath.suffix == ".json":
            obj.to_json(filepath)
        elif filepath.suffix == ".parquet":
            obj.to_parquet(filepath)
        elif filepath.suffix == ".xlsx" or filepath.suffix == ".xls":
            obj.to_excel(filepath)
        elif filepath.suffix == ".xml":
            obj.to_xml(filepath)
        elif filepath.suffix == ".sql":
            obj.to_sql(filepath)
        else:
            obj.to_pickle(filepath)

    def _deserialize_pandas(filepath: Path) -> pd.DataFrame:
        if filepath.suffix == ".csv":
            return pd.read_csv(filepath)
        elif filepath.suffix == ".json":
            return pd.read_json(filepath)
        elif filepath.suffix == ".parquet":
            return pd.read_parquet(filepath)
        elif filepath.suffix == ".xlsx" or filepath.suffix == ".xls":
            return pd.read_excel(filepath)
        elif filepath.suffix == ".xml":
            return pd.read_xml(filepath)
        elif filepath.suffix == ".sql":
            return pd.read_sql(filepath)
        else:
            return pd.read_pickle(filepath)

    # TODO Read from file function

except ImportError:
    wandb.termwarn(
        "Warning: `pandas` is not installed. Logging dataframes as Artifacts may not work."
    )

# Tensorflow Models
try:
    import tensorflow as tf

    @typedispatch
    def _serialize(filepath: Path, obj: tf.keras.Model) -> None:
        obj.save(filepath)

    def _deserialize_tensorflow(filepath: Path) -> tf.keras.Model:
        return tf.keras.models.load_model(filepath)

except ImportError:
    wandb.termwarn(
        "Warning: `tensorflow` is not installed. Logging Tensorflow models as Artifacts may not work."
    )

# PyTorch Tensors and Models
try:
    import torch

    @typedispatch
    def _serialize(filepath: Path, obj: Union[torch.Tensor, torch.nn.Module]) -> None:
        torch.save(obj, filepath)

    def _deserialize_torch(filepath: Path) -> Union[torch.Tensor, torch.nn.Module]:
        return torch.load(filepath)

except ImportError:
    wandb.termwarn(
        "Warning: `torch` is not installed. Logging torch Tensors as Artifacts may not work."
    )

# Pickle Objects - Default
@typedispatch
def _serialize(filepath: Path, obj: Any) -> None:
    with open(filepath, "wb") as f:
        pickle.dump(obj, f)

def _deserialize_pickle(filepath: Path) -> Any:
    with open(filepath, "rb") as f:
        return pickle.load(f)

def _deserialize(filepath: Path) -> Any:
    if filepath.suffix in [".npy", ".npz"]:
        return _deserialize_numpy(filepath)
    elif filepath.suffix in [".csv", ".json", ".parquet", ".xlsx", ".xls", ".xml", ".sql"]:
        return _deserialize_pandas(filepath)
    elif filepath.suffix in [".pt", ".pth"]:
        return _deserialize_torch(filepath)
    elif filepath.suffix in ['.h5', '.hdf5']:
        return _deserialize_tensorflow(filepath)
    else:
        return _deserialize_pickle(filepath)


class WandbArtifact(AbstractDataSet):
    """
    WandbArtifact loads from/to a Wandb Artifact using the underlying Filesystem
    """

    def __init__(
        self,
        artifact_name: str,
        artifact_type: str,
        filepath: str,
        alias: Optional[str] = "latest",  # TODO List of aliases
        override: Optional[bool] = True,
    ) -> None:
        super(WandbArtifact, self).__init__()

        self.artifact_name = artifact_name
        self.artifact_type = artifact_type
        self.alias = alias
        self.filepath = Path(filepath)
        self.override = override
        self.entity = None
        self.project = None
        self.run = None

    def _describe(self) -> Dict[str, Any]:
        return {
            "type": "wandb_artifact",
            "entity": self.entity,
            "project": self.project,
            "artifact_name": self.artifact_name,
            "alias": self.alias,
        }

    def _load(self) -> Any:
        artifact = self.run.use_artifact(f"{self.artifact_name}:{self.alias}")

        if artifact is None:
            raise Exception(
                f"Artifact {self.artifact_name} does not exist in {self.run.project_name()}"
            )

        if self.override:
            # Any existing files in `root` are remained untouched by default.
            # If `override` is set to True, existing files in `root` are deleted
            # before downloading artifact.
            if self.filepath.is_file():
                self.filepath.unlink()

        artifact.download(self.filepath.parent)

        return _deserialize(self.filepath)

    def _save(self, data: Any) -> None:
        artifact = wandb.Artifact(
            self.artifact_name, type=self.artifact_type
        )

        if self.override:
            if self.filepath.is_file():
                self.filepath.unlink()
        # serialize data to self.filepath based on the type of data
        _serialize(self.filepath, data)

        if self.filepath.is_file():
            artifact.add_file(self.filepath)

        if self.run:
            self.run.log_artifact(artifact)

        # Wait for artifact to be uploaded
        artifact.wait()
