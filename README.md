# Experimental wandb client
---

Progress

API:
 - [ ] wandb.init() basic
 - [ ] wandb.log() basic
 - [ ] wandb.join() basic
 - [ ] wandb.run basic
 - [ ] wandb.config basic
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


## Features

### standardize all CLI->backend updates

Alternatives:
- RPC
- multiprocessing queue

