---
description: API is a class used to access data from wandb
---

# API

### API Methods

| Method | Params | Description |
| :--- | :--- | :--- |
| init | _overrides={"username": None, "project": None}_ | Accepts optional setting overrides. If you specify username and project here you don't need to include them in the paths. |
| run | _path=""_ | Returns a Run object given a path. If can be run\_id if a global username and project is set. |
| runs | _path="", filters={}_ | Returns a Runs object given a path to a project and optional filters. |
| create\_run | _project=None, username=None, run\_id=None_ | Returns a new run object after creating it on the server. |

### Example Usage

```python
import wandb
api = wandb.Api()
```

