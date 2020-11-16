---
title: Artifacts
---

<a name="wandb.sdk.wandb_artifacts"></a>
# wandb.sdk.wandb\_artifacts

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L2)

<a name="wandb.sdk.wandb_artifacts.ArtifactsCache"></a>
## ArtifactsCache Objects

```python
class ArtifactsCache(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L35)

<a name="wandb.sdk.wandb_artifacts.ArtifactsCache.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(cache_dir)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L36)

<a name="wandb.sdk.wandb_artifacts.ArtifactsCache.check_md5_obj_path"></a>
#### check\_md5\_obj\_path

```python
 | check_md5_obj_path(b64_md5, size)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L42)

<a name="wandb.sdk.wandb_artifacts.ArtifactsCache.check_etag_obj_path"></a>
#### check\_etag\_obj\_path

```python
 | check_etag_obj_path(etag, size)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L50)

<a name="wandb.sdk.wandb_artifacts.get_artifacts_cache"></a>
#### get\_artifacts\_cache

```python
get_artifacts_cache()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L61)

<a name="wandb.sdk.wandb_artifacts.Artifact"></a>
## Artifact Objects

```python
class Artifact(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L69)

An artifact object you can write files into, and pass to log_artifact.

<a name="wandb.sdk.wandb_artifacts.Artifact.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(name, type, description=None, metadata=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L72)

<a name="wandb.sdk.wandb_artifacts.Artifact.id"></a>
#### id

```python
 | @property
 | id()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L108)

<a name="wandb.sdk.wandb_artifacts.Artifact.entity"></a>
#### entity

```python
 | @property
 | entity()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L113)

<a name="wandb.sdk.wandb_artifacts.Artifact.project"></a>
#### project

```python
 | @property
 | project()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L118)

<a name="wandb.sdk.wandb_artifacts.Artifact.manifest"></a>
#### manifest

```python
 | @property
 | manifest()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L122)

<a name="wandb.sdk.wandb_artifacts.Artifact.digest"></a>
#### digest

```python
 | @property
 | digest()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L127)

<a name="wandb.sdk.wandb_artifacts.Artifact.new_file"></a>
#### new\_file

```python
 | new_file(name, mode="w")
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L136)

<a name="wandb.sdk.wandb_artifacts.Artifact.add_file"></a>
#### add\_file

```python
 | add_file(local_path, name=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L145)

<a name="wandb.sdk.wandb_artifacts.Artifact.add_dir"></a>
#### add\_dir

```python
 | add_dir(local_path, name=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L161)

<a name="wandb.sdk.wandb_artifacts.Artifact.add_reference"></a>
#### add\_reference

```python
 | add_reference(uri, name=None, checksum=True, max_objects=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L204)

<a name="wandb.sdk.wandb_artifacts.Artifact.add"></a>
#### add

```python
 | add(obj, name)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L229)

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

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L278)

If local_path was already added to artifact, return its internal name.

<a name="wandb.sdk.wandb_artifacts.Artifact.get_path"></a>
#### get\_path

```python
 | get_path(name)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L285)

<a name="wandb.sdk.wandb_artifacts.Artifact.download"></a>
#### download

```python
 | download()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L288)

<a name="wandb.sdk.wandb_artifacts.Artifact.finalize"></a>
#### finalize

```python
 | finalize()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L291)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1"></a>
## ArtifactManifestV1 Objects

```python
class ArtifactManifestV1(ArtifactManifest)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L328)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1.version"></a>
#### version

```python
 | @classmethod
 | version(cls)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L330)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1.from_manifest_json"></a>
#### from\_manifest\_json

```python
 | @classmethod
 | from_manifest_json(cls, artifact, manifest_json)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L334)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(artifact, storage_policy, entries=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L363)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1.to_manifest_json"></a>
#### to\_manifest\_json

```python
 | to_manifest_json()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L368)

This is the JSON that's stored in wandb_manifest.json

If include_local is True we also include the local paths to files. This is
used to represent an artifact that's waiting to be saved on the current
system. We don't need to include the local paths in the artifact manifest
contents.

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestV1.digest"></a>
#### digest

```python
 | digest()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L397)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestEntry"></a>
## ArtifactManifestEntry Objects

```python
class ArtifactManifestEntry(object)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L405)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestEntry.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(path, ref, digest, birth_artifact_id=None, size=None, extra=None, local_path=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L406)

<a name="wandb.sdk.wandb_artifacts.ArtifactManifestEntry.__repr__"></a>
#### \_\_repr\_\_

```python
 | __repr__()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L430)

<a name="wandb.sdk.wandb_artifacts.WandbStoragePolicy"></a>
## WandbStoragePolicy Objects

```python
class WandbStoragePolicy(StoragePolicy)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L439)

<a name="wandb.sdk.wandb_artifacts.WandbStoragePolicy.name"></a>
#### name

```python
 | @classmethod
 | name(cls)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L441)

<a name="wandb.sdk.wandb_artifacts.WandbStoragePolicy.from_config"></a>
#### from\_config

```python
 | @classmethod
 | from_config(cls, config)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L445)

<a name="wandb.sdk.wandb_artifacts.WandbStoragePolicy.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(config=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L448)

<a name="wandb.sdk.wandb_artifacts.WandbStoragePolicy.config"></a>
#### config

```python
 | config()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L473)

<a name="wandb.sdk.wandb_artifacts.WandbStoragePolicy.load_file"></a>
#### load\_file

```python
 | load_file(artifact, name, manifest_entry)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L476)

<a name="wandb.sdk.wandb_artifacts.WandbStoragePolicy.store_reference"></a>
#### store\_reference

```python
 | store_reference(artifact, path, name=None, checksum=True, max_objects=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L495)

<a name="wandb.sdk.wandb_artifacts.WandbStoragePolicy.load_reference"></a>
#### load\_reference

```python
 | load_reference(artifact, name, manifest_entry, local=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L502)

<a name="wandb.sdk.wandb_artifacts.WandbStoragePolicy.store_file"></a>
#### store\_file

```python
 | store_file(artifact_id, entry, preparer, progress_callback=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L525)

<a name="wandb.sdk.wandb_artifacts.__S3BucketPolicy"></a>
## \_\_S3BucketPolicy Objects

```python
class __S3BucketPolicy(StoragePolicy)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L558)

<a name="wandb.sdk.wandb_artifacts.__S3BucketPolicy.name"></a>
#### name

```python
 | @classmethod
 | name(cls)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L560)

<a name="wandb.sdk.wandb_artifacts.__S3BucketPolicy.from_config"></a>
#### from\_config

```python
 | @classmethod
 | from_config(cls, config)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L564)

<a name="wandb.sdk.wandb_artifacts.__S3BucketPolicy.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(bucket)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L569)

<a name="wandb.sdk.wandb_artifacts.__S3BucketPolicy.config"></a>
#### config

```python
 | config()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L578)

<a name="wandb.sdk.wandb_artifacts.__S3BucketPolicy.load_path"></a>
#### load\_path

```python
 | load_path(artifact, manifest_entry, local=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L581)

<a name="wandb.sdk.wandb_artifacts.__S3BucketPolicy.store_path"></a>
#### store\_path

```python
 | store_path(artifact, path, name=None, checksum=True, max_objects=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L584)

<a name="wandb.sdk.wandb_artifacts.MultiHandler"></a>
## MultiHandler Objects

```python
class MultiHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L590)

<a name="wandb.sdk.wandb_artifacts.MultiHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(handlers=None, default_handler=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L591)

<a name="wandb.sdk.wandb_artifacts.MultiHandler.scheme"></a>
#### scheme

```python
 | @property
 | scheme()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L600)

<a name="wandb.sdk.wandb_artifacts.MultiHandler.load_path"></a>
#### load\_path

```python
 | load_path(artifact, manifest_entry, local=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L603)

<a name="wandb.sdk.wandb_artifacts.MultiHandler.store_path"></a>
#### store\_path

```python
 | store_path(artifact, path, name=None, checksum=True, max_objects=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L617)

<a name="wandb.sdk.wandb_artifacts.TrackingHandler"></a>
## TrackingHandler Objects

```python
class TrackingHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L636)

<a name="wandb.sdk.wandb_artifacts.TrackingHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L637)

Tracks paths as is, with no modification or special processing. Useful
when paths being tracked are on file systems mounted at a standardized
location.

For example, if the data to track is located on an NFS share mounted on
/data, then it is sufficient to just track the paths.

<a name="wandb.sdk.wandb_artifacts.TrackingHandler.scheme"></a>
#### scheme

```python
 | @property
 | scheme()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L649)

<a name="wandb.sdk.wandb_artifacts.TrackingHandler.load_path"></a>
#### load\_path

```python
 | load_path(artifact, manifest_entry, local=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L652)

<a name="wandb.sdk.wandb_artifacts.TrackingHandler.store_path"></a>
#### store\_path

```python
 | store_path(artifact, path, name=None, checksum=False, max_objects=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L664)

<a name="wandb.sdk.wandb_artifacts.DEFAULT_MAX_OBJECTS"></a>
#### DEFAULT\_MAX\_OBJECTS

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L679)

<a name="wandb.sdk.wandb_artifacts.LocalFileHandler"></a>
## LocalFileHandler Objects

```python
class LocalFileHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L682)

Handles file:// references

<a name="wandb.sdk.wandb_artifacts.LocalFileHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L686)

Tracks files or directories on a local filesystem. Directories
are expanded to create an entry for each file contained within.

<a name="wandb.sdk.wandb_artifacts.LocalFileHandler.scheme"></a>
#### scheme

```python
 | @property
 | scheme()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L695)

<a name="wandb.sdk.wandb_artifacts.LocalFileHandler.load_path"></a>
#### load\_path

```python
 | load_path(artifact, manifest_entry, local=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L698)

<a name="wandb.sdk.wandb_artifacts.LocalFileHandler.store_path"></a>
#### store\_path

```python
 | store_path(artifact, path, name=None, checksum=True, max_objects=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L723)

<a name="wandb.sdk.wandb_artifacts.S3Handler"></a>
## S3Handler Objects

```python
class S3Handler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L774)

<a name="wandb.sdk.wandb_artifacts.S3Handler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L775)

<a name="wandb.sdk.wandb_artifacts.S3Handler.scheme"></a>
#### scheme

```python
 | @property
 | scheme()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L782)

<a name="wandb.sdk.wandb_artifacts.S3Handler.init_boto"></a>
#### init\_boto

```python
 | init_boto()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L785)

<a name="wandb.sdk.wandb_artifacts.S3Handler.versioning_enabled"></a>
#### versioning\_enabled

```python
 | versioning_enabled(bucket)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L806)

<a name="wandb.sdk.wandb_artifacts.S3Handler.load_path"></a>
#### load\_path

```python
 | load_path(artifact, manifest_entry, local=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L814)

<a name="wandb.sdk.wandb_artifacts.S3Handler.store_path"></a>
#### store\_path

```python
 | store_path(artifact, path, name=None, checksum=True, max_objects=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L866)

<a name="wandb.sdk.wandb_artifacts.GCSHandler"></a>
## GCSHandler Objects

```python
class GCSHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L966)

<a name="wandb.sdk.wandb_artifacts.GCSHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L967)

<a name="wandb.sdk.wandb_artifacts.GCSHandler.versioning_enabled"></a>
#### versioning\_enabled

```python
 | versioning_enabled(bucket)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L973)

<a name="wandb.sdk.wandb_artifacts.GCSHandler.scheme"></a>
#### scheme

```python
 | @property
 | scheme()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L983)

<a name="wandb.sdk.wandb_artifacts.GCSHandler.init_gcs"></a>
#### init\_gcs

```python
 | init_gcs()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L986)

<a name="wandb.sdk.wandb_artifacts.GCSHandler.load_path"></a>
#### load\_path

```python
 | load_path(artifact, manifest_entry, local=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1002)

<a name="wandb.sdk.wandb_artifacts.GCSHandler.store_path"></a>
#### store\_path

```python
 | store_path(artifact, path, name=None, checksum=True, max_objects=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1041)

<a name="wandb.sdk.wandb_artifacts.HTTPHandler"></a>
## HTTPHandler Objects

```python
class HTTPHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1108)

<a name="wandb.sdk.wandb_artifacts.HTTPHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(session, scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1109)

<a name="wandb.sdk.wandb_artifacts.HTTPHandler.scheme"></a>
#### scheme

```python
 | @property
 | scheme()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1115)

<a name="wandb.sdk.wandb_artifacts.HTTPHandler.load_path"></a>
#### load\_path

```python
 | load_path(artifact, manifest_entry, local=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1118)

<a name="wandb.sdk.wandb_artifacts.HTTPHandler.store_path"></a>
#### store\_path

```python
 | store_path(artifact, path, name=None, checksum=True, max_objects=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1144)

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler"></a>
## WBArtifactHandler Objects

```python
class WBArtifactHandler(StorageHandler)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1172)

Handles loading and storing Artifact reference-type files

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler.__init__"></a>
#### \_\_init\_\_

```python
 | __init__(scheme=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1175)

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler.scheme"></a>
#### scheme

```python
 | @property
 | scheme()
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1180)

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler.parse_path"></a>
#### parse\_path

```python
 | @staticmethod
 | parse_path(path)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1184)

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler.load_path"></a>
#### load\_path

```python
 | load_path(artifact, manifest_entry, local=False)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1188)

<a name="wandb.sdk.wandb_artifacts.WBArtifactHandler.store_path"></a>
#### store\_path

```python
 | store_path(artifact, path, name=None, checksum=True, max_objects=None)
```

[[view_source]](https://github.com/wandb/client/blob/bf98510754bad9e6e2b3e857f123852841a4e7ed/wandb/sdk/wandb_artifacts.py#L1212)

