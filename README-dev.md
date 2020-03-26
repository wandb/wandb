# Experimental wandb client

https://paper.dropbox.com/doc/Cling-CLI-Refactor-lETNuiP0Rax8yjTi03Scp

## Play along

`pip install --upgrade git+ssh://git@github.com/wandb/client-ng.git#egg=wandb-ng`

Or from pypi test (last devel release - might be out of date):

- https://test.pypi.org/project/wandb-ng/
- `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple --upgrade wandb-ng`

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
wandb/stuff              - Stuff copied from wandb-og, needs to be refactored or find a place
wandb/agent              - agent/super agent stuff
wandb/framework/keras    - keras integration
wandb/framework/pytorch  - pytorch integration
```

## Code checks

 - Reformat: `tox -e reformat`
 - Type check: `tox -e mypy`
 - Misc: `tox`

## Tasks

 - [ ] Improve hybrid (poor connectivity mode) - jhr
 - [X] Add metadata sync - jhr
 - [X] Add system metrics - jhr
 - [X] Add summary metrics mirror - jhr
 - [x] Add file sync
 - [X] Add media logging
 - [x] Add keras framework
 - [ ] Add code saving
 - [ ] Add pytorch framework
 - [ ] Add other frameworks
 - [ ] Basic CLI functionality
 - [ ] Support modes
 - [ ] Offline sync - jhr

## Progress

API:
 - [x] wandb.init() basic
 - [x] wandb.log() basic
 - [x] wandb.join() basic
 - [x] wandb.run basic
 - [x] wandb.config basic
 - [ ] wandb.save()
 - [ ] wandb.restore()
 - [ ] wandb.init() full
 - [ ] wandb.log() full
 - [ ] wandb.join() full
 - [ ] wandb.run full
 - [ ] wandb.config full
 - [ ] wandb.sweep()
 - [ ] wandb.agent()
 - [ ] wandb.controller()
 
CLI:
 - [ ] wandb login
 - [ ] wandb sync

Functionality:
 - [X] system metrics
 - [x] console log
 - [ ] offline
 - [ ] Unit tests
 - [ ] code coverage

Goals:
 - [ ] standardize all CLI->backend updates
 - [ ] reorganize code to avoid different contexts (run_manager)
 - [ ] jupyter simplification using request queues or RPC
 - [ ] utilize more standard methods for background process
 - [ ] better isolation for extended features (system monitoring, git logging)
 - [ ] offline support improvements: enforce constraints at sync time (code logging, etc)
 - [ ] internal api becomes fully internal, only used by "internal" process
 - [ ] telemetry of all operations
 
Bonus:
- [ ] multi-language synchronizer
- [ ] schema'ed binary? cloud? log for offline run data
- [ ] less (no) dependance on local filesytem
- [ ] type annotations
- [ ] cleaned up logger
