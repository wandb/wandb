---
title: Artifacts
---

<a name="wandb.sdk.wandb_artifacts"></a>
# wandb.sdk.wandb\_artifacts

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L2)

<a name="wandb.sdk.wandb_artifacts.Artifact"></a>
## Artifact Objects

```python
class Artifact(object)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L69)

An artifact object you can write files into, and pass to log_artifact.

<a name="wandb.sdk.wandb_artifacts.Artifact.add"></a>
#### add

```python
 | add(obj, name)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L229)

Adds `obj` to the artifact, located at `name`. You can use Artifact#get(`name`) after downloading
the artifact to retrieve this object.

**Arguments**:

- `obj` _wandb.Media_ - The object to save in an artifact
- `name` _str_ - The path to save

<a name="wandb.sdk.wandb_artifacts.Artifact.get_added_local_path_name"></a>
#### get\_added\_local\_path\_name

```python
 | get_added_local_path_name(local_path)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L278)

If local_path was already added to artifact, return its internal name.

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1"></a>
## ArtifactManifestV1 Objects

```python
class ArtifactManifestV1(ArtifactManifest)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L328)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1.to_manifest_json"></a>
#### to\_manifest\_json

```python
 | to_manifest_json()
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L368)

This is the JSON that's stored in wandb_manifest.json

If include_local is True we also include the local paths to files. This is
used to represent an artifact that's waiting to be saved on the current
system. We don't need to include the local paths in the artifact manifest
contents.

<a name="wandb.sdk.wandb_artifacts.TrackingHandler"></a>
## TrackingHandler Objects

```python
class TrackingHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L636)

<a name="wandb.sdk.wandb_artifacts.TrackingHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L637)

Tracks paths as is, with no modification or special processing. Useful
when paths being tracked are on file systems mounted at a standardized
location.

For example, if the data to track is located on an NFS share mounted on
/data, then it is sufficient to just track the paths.

<a name="wandb.sdk.wandb_artifacts.LocalFileHandler"></a>
## LocalFileHandler Objects

```python
class LocalFileHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L682)

Handles file:// references

<a name="wandb.sdk.wandb_artifacts.LocalFileHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L686)

Tracks files or directories on a local filesystem. Directories
are expanded to create an entry for each file contained within.

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler"></a>
## WBArtifactHandler Objects

```python
class WBArtifactHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/4a4de49c33117fcbb069439edeb509d54fd41176/wandb/sdk/wandb_artifacts.py#L1172)

Handles loading and storing Artifact reference-type files

