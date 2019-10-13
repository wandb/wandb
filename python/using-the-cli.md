---
description: >-
  Log in, restore code state, sync local directories to our servers, and run
  hyperparameter sweeps with our command line interface
---

# Command Line Interface

After running `pip install wandb` you should have a new command available, **wandb**. 

The following sub-commands are available:

| Sub-command | Description |
| :--- | :--- |
| docs | Open documentation in a browser |
| init | Configure a directory with W&B |
| login | Login to W&B |
| off | Disable W&B in this directory, useful for testing |
| on | Ensure W&B is enabled in this directory |
| docker | Run a docker image, mount cwd, and ensure wandb is installed |
| docker-run | Add W&B environment variables to a docker run command |
| projects | List projects |
| pull | Pull files for a run from W&B |
| restore | Restore code and config state for a run |
| run | Launch a job, required on Windows |
| runs | List runs in a project |
| sync | Sync a local directory containing tfevents or previous runs files |
| status | List current directory status |
| sweep | Create a new sweep given a YAML definition |
| agent | Start an agent to run programs in the sweep |

## Restore the state of your code

Use `restore` to return to the state of your code when you ran a given run.

#### Example

```text
# creates a branch and restores the code to the state it was in when run $RUN_ID was executed
wandb restore $RUN_ID
```

**How do we capture the state of the code?**

When `wandb.init` is called from your script, a link is saved to the last git commit if the code is in a git repository. A diff patch is also created in case there are uncommitted changes or changes that are out of sync with your remote.

