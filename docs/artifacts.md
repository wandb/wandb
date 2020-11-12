---
title: Artifacts
---

<a name="wandb.sdk.wandb_artifacts"></a>
# wandb.sdk.wandb\_artifacts

[[view_source]](https://github.com/wandb/client/blob/da00d67e47b7a5e243474acb20bf17b406da59b8/wandb/sdk/wandb_artifacts.py#L2)

<a name="wandb.sdk.wandb_artifacts.Artifact"></a>
## Artifact Objects

```python
class Artifact(object)
```

[[view_source]](https://github.com/wandb/client/blob/da00d67e47b7a5e243474acb20bf17b406da59b8/wandb/sdk/wandb_artifacts.py#L69)

An artifact object you can write files into, and pass to log_artifact.

<a name="wandb.sdk.wandb_artifacts.Artifact.add"></a>
#### add

```python
 | add(obj, name)
```

[[view_source]](https://github.com/wandb/client/blob/da00d67e47b7a5e243474acb20bf17b406da59b8/wandb/sdk/wandb_artifacts.py#L229)

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

[[view_source]](https://github.com/wandb/client/blob/da00d67e47b7a5e243474acb20bf17b406da59b8/wandb/sdk/wandb_artifacts.py#L278)

If local_path was already added to artifact, return its internal name.

