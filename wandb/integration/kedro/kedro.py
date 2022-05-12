import wandb
from pathlib import Path
from typing import Optional, Dict, Union, Any
import pickle
 
try:
    from kedro.io import AbstractDataSet
    from kedro.io import DataCatalog
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
        wandb_params = catalog.load("parameters")["wandb"]
        entity = wandb_params["entity"]
        project = wandb_params["project"]
        mode = wandb_params["mode"]
 
        # TODO Other metrics go in wandb config
 
        # TODO Use catalog.list to get all the keys, and load all parameters into a wandb config
        # TODO Proper exception handling
 
        self.run = wandb.init(project=project, entity=entity, mode=mode)
 
        for parameter in catalog.list("parameters"):
            if not parameter.startswith("wandb"):  # TEST how this works with dicts
                self.run.config[parameter] = catalog.load(parameter)
 
        for dataset in catalog._data_sets.values():
            # Iterating through every dataset object in the catalog to pass in wandb properties
            if isinstance(dataset, WandbArtifact):
                dataset.run = self.run
                dataset.entity = entity
                dataset.project = project
 
    @hook_impl
    def after_pipeline_run(self) -> None:
        self.run.finish()
 
 
# Numpy Arrays
try:
    import numpy as np
 
    @typedispatch
    def _serialize(filepath: Path, obj: np.ndarray) -> None:
        ic("Serializing Numpy Array", filepath)
        np.save(filepath, obj)
 
    # TODO Read from file function
 
except ImportError:
    wandb.termwarn(
        "Warning: `numpy` is not installed. Logging arrays as Artifacts may not work."
    )
 
try:
    import pandas as pd
 
    @typedispatch
    def _serialize(filepath: Path, obj: pd.DataFrame) -> None:
        ic("Serializing Pandas DataFrame", filepath)
        if filepath.suffix == ".csv":
            obj.to_csv(filepath)
        elif filepath.suffix == ".json":
            obj.to_json(filepath)
        elif filepath.suffix == ".parquet":
            obj.to_parquet(filepath)
        elif filepath.suffix == ".json":
            obj.to_json(filepath)
        elif filepath.suffix == ".xlsx" or filepath.suffix == ".xls":
            obj.to_excel(filepath)
        elif filepath.suffix == ".xml":
            obj.to_xml(filepath)
        elif filepath.suffix == ".sql":
            obj.to_sql(filepath)
        else:
            obj.to_pickle(filepath)
 
    # TODO Read from file function
 
except ImportError:
    wandb.termwarn(
        "Warning: `pandas` is not installed. Logging dataframes as Artifacts may not work."
    )
 
# PyTorch Tensors and Models
try:
    import torch
 
    @typedispatch
    def _serialize(filepath: Path, obj: Union[torch.Tensor, torch.nn.Module]) -> None:
        ic("Serializing PyTorch Tensor", filepath)
        torch.save(obj, filepath)
 
    # TODO Read from file function
 
except ImportError:
    wandb.termwarn(
        "Warning: `torch` is not installed. Logging torch Tensors as Artifacts may not work."
    )
 
# Sklearn Models
try:
    import sklearn
 
    @typedispatch
    def _serialize(filepath: Path, obj: sklearn.base.BaseEstimator) -> None:
        ic("Serializing Scikit-Learn Model", filepath)
        obj.save(filepath)
 
    # TODO Read from file function
except ImportError:
    wandb.termwarn(
        "Warning: `sklearn` is not installed. Logging Scikit-Learn Models as Artifacts may not work."
    )
 
# Pickle Objects - Default
@typedispatch
def _serialize(filepath: Path, obj: Any) -> None:
    with open(filepath, "wb") as f:
        pickle.dump(obj, f)
 
 
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
        override: Optional[bool] = False,
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
 
    def _load(self) -> Any:  # TODO Load
        artifact = self.run.use_artifact(self.artifact_name)
 
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
 
        artifact.download(self.filepath)
 
        return self.filepath  # TODO Deserialize and return object
 
    def _save(self, data: Any) -> None:
        artifact = wandb.Artifact(
            self.artifact_name, type="KedroDataset"
        )  # TODO change KedroDataset
 
        # serialize data to self.filepath based on the type of data
        _serialize(self.filepath, data)
 
        if self.filepath.is_file():
            artifact.add_file(self.filepath)
 
        if self.run:
            self.run.log_artifact(artifact)
