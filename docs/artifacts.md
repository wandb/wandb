---
title: Artifacts
---

<a name="wandb.sdk.wandb_artifacts"></a>
# wandb.sdk.wandb\_artifacts

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_artifacts.py#L2)

<a name="wandb.sdk.wandb_artifacts.Artifact"></a>
## Artifact Objects

```python
class Artifact(object)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_artifacts.py#L69)

An artifact object you can write files into, and pass to log_artifact.

<a name="wandb.sdk.wandb_artifacts.Artifact.add"></a>
#### add

```python
 | add(obj, name)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_artifacts.py#L229)

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

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_artifacts.py#L278)

If local_path was already added to artifact, return its internal name.

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1"></a>
## ArtifactManifestV1 Objects

```python
class ArtifactManifestV1(ArtifactManifest)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_artifacts.py#L328)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1.to_manifest_json"></a>
#### to\_manifest\_json

```python
 | to_manifest_json()
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_artifacts.py#L368)

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

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_artifacts.py#L636)

<a name="wandb.sdk.wandb_artifacts.TrackingHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_artifacts.py#L637)

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

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_artifacts.py#L682)

Handles file:// references

<a name="wandb.sdk.wandb_artifacts.LocalFileHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_artifacts.py#L686)

Tracks files or directories on a local filesystem. Directories
are expanded to create an entry for each file contained within.

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler"></a>
## WBArtifactHandler Objects

```python
class WBArtifactHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_artifacts.py#L1172)

Handles loading and storing Artifact reference-type files

<a name="wandb.sdk.wandb_run"></a>
# wandb.sdk.wandb\_run

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_run.py#L4)

<a name="wandb.sdk.wandb_run.Run"></a>
## Run Objects

```python
class Run(object)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_run.py#L132)

The run object corresponds to a single execution of your script,
typically this is an ML experiment. Create a run with wandb.init().

In distributed training, use wandb.init() to create a run for each process,
and set the group argument to organize runs into a larger experiment.

Currently there is a parallel Run object in the wandb.Api. Eventually these
two objects will be merged.

**Attributes**:

- `history` _`History`_ - Time series values, created with wandb.log().
History can contain scalar values, rich media, or even custom plots
across multiple steps.
- `summary` _`Summary`_ - Single values set for each wandb.log() key. By
default, summary is set to the last value logged. You can manually
set summary to the best value, like max accuracy, instead of the
final value.

<a name="wandb.sdk.wandb_run.Run.use_artifact"></a>
#### use\_artifact

```python
 | use_artifact(artifact_or_name, type=None, aliases=None)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_run.py#L1552)

Declare an artifact as an input to a run, call `download` or `file` on \
the returned object to get the contents locally.

**Arguments**:

- `artifact_or_name` _str or Artifact_ - An artifact name.
May be prefixed with entity/project. Valid names
can be in the following forms:
name:version
name:alias
digest
You can also pass an Artifact object created by calling `wandb.Artifact`
- `type` _str, optional_ - The type of artifact to use.
- `aliases` _list, optional_ - Aliases to apply to this artifact

**Returns**:

A `Artifact` object.

<a name="wandb.sdk.wandb_run.Run.log_artifact"></a>
#### log\_artifact

```python
 | log_artifact(artifact_or_path, name=None, type=None, aliases=None)
```

[[view_source]](https://github.com/wandb/client/blob/403753e61ca40db2f811b5026ad1e6a5b85bbc15/wandb/sdk/wandb_run.py#L1607)

Declare an artifact as output of a run.

**Arguments**:

- `artifact_or_path` _str or Artifact_ - A path to the contents of this artifact,
can be in the following forms:
/local/directory
/local/directory/file.txt
s3://bucket/path
You can also pass an Artifact object created by calling
`wandb.Artifact`.
- `name` _str, optional_ - An artifact name. May be prefixed with entity/project.
Valid names can be in the following forms:
name:version
name:alias
digest
This will default to the basename of the path prepended with the current
run id  if not specified.
- `type` _str_ - The type of artifact to log, examples include "dataset", "model"
- `aliases` _list, optional_ - Aliases to apply to this artifact,
defaults to ["latest"]


**Returns**:

A `Artifact` object.

