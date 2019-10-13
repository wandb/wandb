---
description: >-
  Restore a file, such as a model checkpoint, into your run folder to access in
  your script
---

# wandb.restore

### Overview

Calling `wandb.restore(filename)` will restore a file into your run. It returns a local file object open for reading.

`wandb.restore` accepts a few keyword arguments:

* **run\_path** — String telling the run to pull from in the format _'$ENTITY\_NAME/$PROJECT\_NAME/$RUN\_NAME'_ or _'$PROJECT\_NAME/$RUN\_NAME'_ \(_default: current entity, project and run_\)

A common use case is resuming from a checkpoint in the case of failure.

Another common use is to restore the model file from a previous run.

### Example

```text
if args.restore:
    wandb.restore('model.h5') # restore from a checkpoint, resuming must be configured
weights = wandb.restore('best.h5', run_path="vanpelt/html/a1b2c3d")
model.load(weights.name)
```

> If you don't specify a run\_path, you'll need to configure [resuming](../advanced-features/resuming.md) for your run. If you want access to files programmatically outside of training, use the [Run API]().

