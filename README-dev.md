# Experimental wandb client

https://paper.dropbox.com/doc/Cling-CLI-Refactor-lETNuiP0Rax8yjTi03Scp

## Play along

`pip install --upgrade git+git://github.com/wandb/client-ng.git#egg=wandb-ng`

Or from pypi:

- https://pypi.org/project/wandb-ng/
- `pip install --upgrade wandb-ng`

## Code organization

```
wandb/sdk                - User accessed functions [wandb.init()] and objects [WandbRun, WandbConfig, WandbSummary, WandbSettings]
wandb/sdk_py27           - Generated files [currently by strip.sh]
wandb/backend            - Support to launch internal process
wandb/interface          - Interface to backend execution 
wandb/proto              - Protocol buffers for inter-process communication and persist file store
wandb/internal           - Backend threads/processes
wandb/apis               - Public api (still has internal api but this should be moved to wandb/internal)
wandb/cli                - Handlers for command line functionality
wandb/superagent         - super agent / run queue work in progress
wandb/sweeps             - sweeps stuff (mostly unmodified for now)
wandb/framework/keras    - keras integration
wandb/framework/pytorch  - pytorch integration
```

## Code checks

 - Reformat: `tox -e format`
 - Type check: `tox -e flake8,mypy`
 - Misc: `tox`

## Library Objectives

### Supported user interface

All objects and methods that users are intended to interact with are in the wand/sdk directory.  Any
method on an object that is not prefixed with an underscore is part of the supported interface and should
be documented.

User interface should be typed using python 3.6+ type annotations.  Older versions will use untyped interface.

### Arguments/environment variables impacting wandb functions are merged with Settings

See below for more about the Settings object.  The primary objective of this design principle is that
behavior of code can be impacted by multiple sources.  These sources need to be merged consistently
and information given to the user when settings are overwritten to inform the user.  Examples of sources
of settings:

 - Enforced settings from organization, team, user, project
 - settings set by environment variables: WANDB_PROJECT=
 - settings passed to wand function: wandb.init(project=)
 - Default settings from organization, team, project
 - settings in global settings file: ~/.config/wandb/settings
 - settings in local settings file: ./wandb/settings

### Data to be synced to server is fully validated

Calls to wandb.log() result in the dictionary being serialized into a schema'ed data structure.
Any non supported element should result in an immediate exception.

### All changes to objects are reflected in sync data

When changing properties of objects, those objects should serialize the changes into a schema'ed data
structure.  There should be no need for .save() methods on objects.

### Library can be disabled

When running in disabled mode, all objects act as in memory stores of attribute information but they do
not perform any serialization to sync data.

## Changes from production library

### wandb.Settings

Main settings object that is passed explicitly or implicitly to all wandb functions

### wandb.setup()

Similar to wandb.init() but it impacts the entire process or session.  This allows multiple wandb.init() calls to share
some common setup.   It is not necessary as it will be called implicitly by the first wandb.init() call.


## Detailed walk through of a simple program

### Program

```
import wandb
run = wandb.init(config=dict(param1=1))
run.config.param2 = 2
run.log(dict(this=3))
```

### Steps

#### wandb.init()

- Creates a Run object (specifically RunManaged)
- Sets a global Run object for users who use wandb.log() syntax
- Returns Run object

TODO(jhr): finish this


## Sync details
