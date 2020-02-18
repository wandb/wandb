# Experimental wandb client
---

Progress

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
- [ ] system metrics
- [ ] console log
- [ ] offline

Goals:
 - [ ] standardize all CLI->backend updates
 - [ ] reorganize code to avoid different contexts (run_manager)
 - [ ] jupyter simplification using request queues or RPC
 - [ ] utilize more standard methods for background process
 - [ ] better isolation for extended features (system monitoring, git logging)
 - [ ] offline support improvements: enforce constraints at sync time (code logging, etc)
 - [ ] internal api becomes fully internal, only used by "internal" process
 
Bonus:
- [ ] multi-language synchronizer
- [ ] schema'ed binary? cloud? log for offline run data
- [ ] less (no) dependance on local filesytem
- [ ] type annotations
- [ ] cleaned up logger


## Features

### standardize all CLI->backend updates

Alternatives:
- RPC
- multiprocessing queue

Install with:
`pip install --upgrade git+ssh://git@github.com/wandb/client-ng.git#egg=wandb`
