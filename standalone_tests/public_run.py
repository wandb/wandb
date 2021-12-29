#!/usr/bin/env python
#
# make sure we access public interfaces for the run object
#

import wandb

def main():
    run = wandb.init(config=dict(this=2, that=4))

    # not allowed
    # run.socket
    # run.pid
    # run.resume
    # run.program
    # run.args
    # run.storage_id

    # TODO: for compatibility
    print(run.mode)
    print(run.offline)
    # future
    #print(run.disabled)

    print(run.id)
    print(run.entity)
    print(run.project)
    print("GRP", run.group)
    print("JT", run.job_type)

    print(run.resumed)

    print(run.tags)
    print(run.sweep_id)
    print(run.config_static)
    print("PATH", run.path)
    run.save()  # odd
    # tested elsewhere
    #run.use_artifact()
    #run.log_artifact()
    run.project_name()
    print(run.get_project_url())
    print(run.get_sweep_url())
    print(run.get_url())
    print(run.name)
    print(run.notes)
    run.name = "dummy"
    # deprecated
    #print(run.description)
    #run.description = "dummy"
    # Not supported
    #print(run.host)
    print(run.dir)
    # Not supported
    #print(run.wandb_dir)

if __name__ == '__main__':
    main()
