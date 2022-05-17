# Wandb Integration with Kedro

Integrating `wandb` with `kedro` is easy. All you need is the following 2 lines of code in your project's `settings.py` file:

```python
from wandb.integration.kedro import WandbHooks

HOOKS = (WandbHooks(),)
```

This will set up the mechanism to initialize a W&B run from a Kedro project. In addition to this, you will need to set up your W&B parameters in your `parameters.yml` file:

```yaml
wandb:
    entity: <YOUR-ENTITY-NAME>
    project: <YOUR-PROJECT-NAME>
    mode: online # Optional, can be set to either online, offline or disabled, but is online by default
```
We will take all other parameters specified in the `parameters.yml` file and upload them to W&B as well.

## Logging Artifacts

You can simply set up an object as an Artifact by using the `wandb.integration.kedro.WandbArtifact` data type. This can be done from the `catalog.yml` file:

```yaml
dataset: # This can be replaced for your dataset's name
    type: wandb.integration.kedro.WandbArtifact
    artifact_name: <ARTIFACT-NAME>
    artifact_type: <ARTIFACT-TYPE>
    filepath: FILE/PATH/HERE
    alias: <ALIAS> # Optional, defaults to "latest"
```

`wandb` will infer the type of file using the file extension provided in the filepath and the type of the object to serialize and deserialize the artifact.