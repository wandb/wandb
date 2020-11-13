# Artifact
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_artifacts.py#L69-L325)

`Artifact`

An artifact object you can write files into, and pass to log_artifact.











## Artifact.add
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_artifacts.py#L229-L276)

`def add(self, obj, name):`

Adds `obj` to the artifact, located at `name`. You can use Artifact#get(`name`) after downloading
the artifact to retrieve this object.


| **Arguments** | **Datatype** | **Description** |
|:--:|:--:|:--|
|obj|(wandb.Media)|The object to save in an artifact|
|name|(str)|The path to save|










## Artifact.get_added_local_path_name
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_artifacts.py#L278-L283)

`def get_added_local_path_name(self, local_path):`

If local_path was already added to artifact, return its internal name.











# ArtifactManifestV1
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_artifacts.py#L328-L402)















## ArtifactManifestV1.to_manifest_json
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_artifacts.py#L368-L394)

`def to_manifest_json(self):`

This is the JSON that's stored in wandb_manifest.json

If include_local is True we also include the local paths to files. This is
used to represent an artifact that's waiting to be saved on the current
system. We don't need to include the local paths in the artifact manifest
contents.












# TrackingHandler
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_artifacts.py#L636-L676)















## TrackingHandler.__init__
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_artifacts.py#L637-L646)

`def __init__(self, scheme=None):`

Tracks files or directories on a local filesystem. Directories
are expanded to create an entry for each file contained within.












# LocalFileHandler
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_artifacts.py#L682-L771)

`LocalFileHandler`

Handles file:// references











## LocalFileHandler.__init__
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_artifacts.py#L686-L692)

`def __init__(self, scheme=None):`

Tracks files or directories on a local filesystem. Directories
are expanded to create an entry for each file contained within.












# WBArtifactHandler
[![Badge](https://img.shields.io/badge/View%20source%20on%20GitHub-black?style=for-the-badge&logo=github)](https://github.com/wandb/client/blob/master/wandb/sdk/wandb_artifacts.py#L1172-L1233)

`WBArtifactHandler`

Handles loading and storing Artifact reference-type files











