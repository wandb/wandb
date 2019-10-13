# API

W&B provides an API to import and export data directly. This is useful for doing custom analysis of your existing runs or running an evaluation script and adding additional summary metrics.

### Authentication

Before using the API you need to store your key locally by running `wandb login` or set the **WANDB\_API\_KEY** environment variable.

### Error Handling

If errors occur while talking to W&B servers a `wandb.CommError` will be raised. The original exception can be introspected via the **exc** attribute.

```

```

