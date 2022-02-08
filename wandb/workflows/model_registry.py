from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
)
import os
import wandb.data_types as data_types
from wandb.sdk.interface.artifacts import (
    ArtifactEntry,
    Artifact as ArtifactInterface,
)
import wandb
from wandb.util import get_module

def log_model(
    model_obj: Any, 
    name: Optional[str]=None, 
    aliases: Optional[Union[str, List[str]]]=None,
    description: Optional[str] = None,
    metadata: Optional[dict] = None,
    project: Optional[str] = None,
    # evaluation_table:Optional[data_types.Table]=None,
    # serialization_strategy=wandb.serializers.PytorchSerializer,
    # link_to_registry=True
    ):
        return _log_artifact_version(
            name=name if name is not None else 'model',
            type="model",
            entries={
                "index": data_types.SavedModel(model_obj),
            },
            aliases=aliases,
            description=description,
            metadata=metadata,
            project=project,
            project_scope = False,
            job_type = "log_model"
        )

def model_versions(model_name: str):
    return wandb.Api().artifact_collection(model_name, "model").versions()

def link_model(model_artifact: Union[str, ArtifactEntry], registered_model: str):
    # TODO: implement this.
    pass

def use_model(model_name: str,
    project: Optional[str] = None,
    job_type: str = "auto"
):
    if wandb.run is None:
        wandb.init(project=project, job_type=job_type, settings=wandb.Settings(silent="true"))

    if ":" not in model_name:
        model_name = f"{model_name}:latest"
    
    art = wandb.run.use_artifact(model_name, type="model")

    return art.get("index")


def _add_any(artifact: ArtifactInterface, 
    path_or_obj: Union[str,ArtifactEntry,data_types.WBValue], #todo: add dataframe
    name: Optional[str]
    # is_tmp: Optional[bool] = False,
    # checksum: bool = True,
    # max_objects: Optional[int] = None,
    ):
    if isinstance(path_or_obj, ArtifactEntry):
        return artifact.add_reference(path_or_obj, name)
    elif isinstance(path_or_obj, data_types.WBValue):
        return artifact.add(path_or_obj, name)
    elif isinstance(path_or_obj, str):
        if os.path.isdir(path_or_obj):
            return artifact.add_dir(path_or_obj)
        elif os.path.isfile(path_or_obj):
            return artifact.add_file(path_or_obj)
        else:
            import json
            with artifact.new_file(name) as f:
                f.write(json.dumps(path_or_obj, sort_keys=True))
    else:
        raise ValueError(f'Expected `path_or_obj` to be instance of `ArtifactEntry`, `WBValue`, or `str, found {type(path_or_obj)}')

def _log_artifact_version(
    name: str,
    type: str,
    entries:Dict[str, Union[str,ArtifactEntry,data_types.WBValue]],
    aliases: Optional[Union[str, List[str]]]=None,
    description: Optional[str] = None,
    metadata: Optional[dict] = None,
    project: Optional[str] = None,
    project_scope: Optional[bool] = None,
    job_type: str = "auto"
) -> ArtifactEntry:
    if wandb.run is None:
        run = wandb.init(project=project, job_type=job_type, settings=wandb.Settings(silent="true"))
    else:
        run = wandb.run

    if not project_scope:
        name = f'{name}-{run.id}'

    art = wandb.Artifact(name, type, description, metadata, False, None)

    for path in entries:
        _add_any(art, entries[path], path)
    
    # Double check that "latest" isn't getting killed.
    if isinstance(aliases, str):
        aliases = [aliases]

    run.log_artifact(art, aliases=aliases)

    return art


def example_pytorch_model(num_classes=10):
    # From https://pytorch.org/tutorials/beginner/saving_loading_models.html
    torch = get_module("torch")
    nn = torch.nn
    optim = torch.optim
    F = nn.functional

    class TheModelClass(nn.Module):
        def __init__(self, num_classes=10):
            super(TheModelClass, self).__init__()
            self.conv1 = nn.Conv2d(3, 6, 5)
            self.pool = nn.MaxPool2d(2, 2)
            self.conv2 = nn.Conv2d(6, 16, 5)
            self.fc1 = nn.Linear(16 * 5 * 5, 120)
            self.fc2 = nn.Linear(120, 84)
            self.fc3 = nn.Linear(84, num_classes)

        def forward(self, x):
            x = self.pool(F.relu(self.conv1(x)))
            x = self.pool(F.relu(self.conv2(x)))
            x = x.view(-1, 16 * 5 * 5)
            x = F.relu(self.fc1(x))
            x = F.relu(self.fc2(x))
            x = self.fc3(x)
            return x
    
    model = TheModelClass(num_classes)
    optimizer = optim.SGD(model.parameters(), lr=0.001, momentum=0.9) 

    return model

# def _entry_is_root_file(path: str):
#     return False

# def _load_artifact(name: str):
#     if ":" not in name:
#         name = name + ":latest"
#     # TODO: workout what happens without runs.
#     art = wandb.run.use_artifact(name)
#     # Fix this ; this is just showing the idea - not actually good implementation.
#     if "index" in art.manifest.entries:
#         return art.get("index")
#     keys = art.manifest.entries.keys()
#     keys.sort()
#     for key in art.manifest.entries.keys():
#         if _entry_is_root_file(key):
#             return art.get(key)

finish = wandb.finish

# # I think we can punt on the table edges and use run lookups....

# import wandb

# from typing import Optional
# from dataclasses import dataclass

# @dataclass()
# class ArtifactType:
#     type_name: str
#     pass

# @dataclass()
# class ArtifactCollection:
#     # artifact_type: ArtifactType
#     artifact_name: str
    

# @dataclass()
# class ArtifactVersion:
#     artifact_collection: ArtifactCollection
#     pass

# @dataclass()
# class _IArtifactNamedType:
#     basename: str

#     @property
#     def _collection(self):
#         return ArtifactCollection(self.basename)

#     @property
#     def _run_scoped_collection(self):
#         if (wandb.run == None):
#             run = wandb.init() # TODO: params
#             #self.run.register_finish_hook(...)
#         else:
#             run = wandb.run
        
#         name = f'run-{run.id}-{self.basename}'
#         return ArtifactCollection(name)

# # Model Reg Python API Workflows:
# py_mod = make_big_3_model()

# '''
# UC 1: 
#     User wishes to log:
#         * 1 model at the end of training
# '''
# # Solution 1: log_model - simple 1 liner convenience function (consider forcing named arguments)
# def log_model(model_obj: Union[pytorch.model, tf.model], name: Optional[str], aliases: Optional[Union[str, List[str]]], metadata: Optional[dict], serialization_strategy: Optional[WBModelSerializationStrategy], run_kwargs: Dict[any], link_to_registry: Optional[Union[bool, str]]):
#     pass

# wandb.log_model(py_mod)
# model_artifact = wandb.log_model(
#     model_obj=py_mod, 
#     name="mnist", 
#     aliases="best", 
#     metadata={"loss", 5}, # should copy current run history as well.
#     evaluation_table=table_or_df,
#     serialization_strategy=wandb.serializers.PytorchSerializer, 
#     run_kwargs={"project": "my_cool_project"},
#     link_to_registry=True)
# # I think this is just going to be a wrapper for "link" or similar.
# wandb.register_model(model_artifact, portfolio_name="my_prod_model")

# wandb.log_model(py_mod)

# wandb._log_artifact_version(
#     artifact_name="artifact_name",
#     artifact_type="type_name",
#     entries={
#         "path": ("uri",)
#     },
#     aliases=["best"],
#     metadata={},
#     entity="entity_name",
#     project="project_name",
# )

# '''
# UC 1.b: 
#     User wishes to log:
#         * 1 model at the end of training
#         * including metadata
# '''

# '''
# UC 1.c
#     User wishes to log:
#         * a model checkpoint periodically
# '''

# '''
# UC 1.d
#     User wishes to log:
#         * a model checkpoint periodically
#         * including metadata & aliases
# '''

# '''
# UC 1.e
#     User wishes to log:
#         * a model checkpoint periodically
#         * and "link" the "best" model to a portfolio
# '''








# # class _IArtifactCollectionSequence(_IArtifactCollection):
# #     pass

# # class _IArtifactCollectionPortfolio(_IArtifactCollection):
# #     pass

# class _ModelArtifactType(_IArtifactType):
#     type_name = 'model'
#     pass

# class _ModelArtifactCollectionPortfolio(_IArtifactCollectionPortfolio):
#     artifact_type = _ModelArtifactType()
#     pass

# class _ModelArtifactCollectionSequence(_IArtifactCollectionSequence):
#     artifact_type = _ModelArtifactType()
#     pass



# class ModelArtifactVersion(_IArtifactVersion):
#     pass

# def model_id_has_alias(model_id: str):
#     return ":" in model_id

# def Model(model_id:str):
#     if model_id_has_alias(model_id):
#         return ModelArtifactVersion(model_id)
#     else
    



#ok, now onto read api:

# maybe we do..
# wandb.use_model("model-name").get("")
# ... hmmm, this might be a good candidate for a "delegation architecture"
# we are going to need to look at the lower level apis and see overlaps. for now, we will need "fetch" function.
# wandb.

# I am thinking just a "load_artifact" method which "uses", then gets the index if it exists, or the alphabetically first non0dir entry.
# defaults to latest.
# If we use the `.as_*` approach, we can punt on figuring out the best model wrapper API.
# model = wandb.load_artifact("my_model").as_pytorch()

# ok, serializers...
# we are going to need a registry. I think that is pretty much it.

# ok, lastly, adding eval data:
# I think this can be solved in the UI:
## Select a model, show all runs which consumed that model and logged a table - show that listing, and have the user select.
## Select second model, default to logically appropriate table, else show options

# wandb.use_model("model-name:alias")


