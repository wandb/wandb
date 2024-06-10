#!/usr/bin/env python
import wandb

"""
Top level:
new_api() -> API (? or sdk or library or core..or not)
default_api
default_session
default_run
(promote methods from default_api, default_session - and maybe default_run to top level namespace?)

API:
  new_session -> Session

Session:
  login()
  configure_auth()
  new_run()
  get_run()  # might have mutable and readonly versions of the run? readonly by default?
  # alternate, prefix with object type? run_new, run_get... dont love
  # ? are api runs just like runapi --> can we log to a run from the public api? why not?

Run:
  log()
  history() -> how does this work for a run in progress


"""

api = wandb.new_api()
session = api.new_session()

run = session.new_run()
run_id = run.id
run.log({"a": 1})
run.finish()

run = session.get_run(run_id)
for _ in run.history():
    pass
