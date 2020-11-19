---
title: Artifacts
---

<a name="wandb.sdk.wandb_artifacts"></a>
# wandb.sdk.wandb\_artifacts

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L2)

<a name="wandb.sdk.wandb_artifacts.Artifact"></a>
## Artifact Objects

```python
class Artifact(object)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L36)

An artifact object you can write files into, and pass to log_artifact.

<a name="wandb.sdk.wandb_artifacts.Artifact.add_reference"></a>
#### add\_reference

```python
 | add_reference(uri, name=None, checksum=True, max_objects=None)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L171)

adds `uri` to the artifact via a reference, located at `name`.
You can use Artifact#get_path(`name`) to retrieve this object.

**Arguments**:

- `uri`:str - the URI path of the reference to add. Can be an object returned from
Artifact.get_path to store a reference to another artifact's entry.
- `name`:str - the path to save

<a name="wandb.sdk.wandb_artifacts.Artifact.add"></a>
#### add

```python
 | add(obj, name)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L206)

Adds `obj` to the artifact, located at `name`. You can use Artifact#get(`name`) after downloading
the artifact to retrieve this object.

**Arguments**:

- `obj` _wandb.WBValue_ - The object to save in an artifact
- `name` _str_ - The path to save

<a name="wandb.sdk.wandb_artifacts.Artifact.get_added_local_path_name"></a>
#### get\_added\_local\_path\_name

```python
 | get_added_local_path_name(local_path)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L249)

If local_path was already added to artifact, return its internal name.

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1"></a>
## ArtifactManifestV1 Objects

```python
class ArtifactManifestV1(ArtifactManifest)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L302)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1.to_manifest_json"></a>
#### to\_manifest\_json

```python
 | to_manifest_json()
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L342)

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

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L609)

<a name="wandb.sdk.wandb_artifacts.TrackingHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L610)

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

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L655)

Handles file:// references

<a name="wandb.sdk.wandb_artifacts.LocalFileHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L659)

Tracks files or directories on a local filesystem. Directories
are expanded to create an entry for each file contained within.

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler"></a>
## WBArtifactHandler Objects

```python
class WBArtifactHandler(StorageHandler)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L1145)

Handles loading and storing Artifact reference-type files

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler.scheme"></a>
#### scheme

```python
 | @property
 | scheme()
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L1154)

overrides parent scheme

**Returns**:

The scheme to which this handler applies.
:rtype: str

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler.load_path"></a>
#### load\_path

```python
 | load_path(artifact, manifest_entry, local=False)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L1167)

Loads the file within the specified artifact given its
corresponding entry. In this case, the referenced artifact is downloaded
and a new symlink is created and returned to the caller.

**Arguments**:

- `manifest_entry`: The index entry to load
:type manifest_entry: ArtifactManifestEntry

**Returns**:

A path to the file represented by `index_entry`
:rtype: os.PathLike

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler.store_path"></a>
#### store\_path

```python
 | store_path(artifact, path, name=None, checksum=True, max_objects=None)
```

[[link string here]](https://github.com/wandb/client/blob/fb5e96d790f1aedcb1f074195e0f7e2209ddc90a/wandb/sdk/wandb_artifacts.py#L1197)

Stores the file or directory at the given path within the specified artifact. In this
case we recursively resolve the reference until the result is a concrete asset so that
we don't have multiple hops. TODO: This resolution could be done in the server for
performance improvements.

**Arguments**:

- `artifact`: The artifact doing the storing
- `path`: The path to store
:type path: str
- `name`: If specified, the logical name that should map to `path`
:type name: str

**Returns**:

A list of manifest entries to store within the artifact
:rtype: list(ArtifactManifestEntry)

