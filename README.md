# Experimental wandb client
---

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

