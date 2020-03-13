import sys
import click

import time

import os
from wandb.apis import internal
import subprocess
import json


class Agent(object):

    def __init__(self, spec):
        self._spec = spec
        settings = dict(base_url="app.qa.wandb.ai")
        self._api = internal.Api(default_settings=settings)

    def check_queue(self):
        entity, project = self._spec.split("/")
        #ups = self._api.pop_from_run_queue(entity="jeff", project="super-agent")
        #print("ent", entity, project)
        try:
            ups = self._api.pop_from_run_queue(entity=entity, project=project)
        except Exception as e:
            print("nothing to run.")
            return None
        return ups

    def run_job(self, job):
        print("agent: got job", job)
        #j = json.loads(job)
        j = job
        cl = j.get("runSpec", {}).get("input", {}).get("config", {})
        c = cl[0]
        #print("got config", c)
        outjson = json.dumps(c)

        with open("config.json", "w") as f:
            print(outjson, file=f)

        command = ["python", "train.py"]
        env=os.environ
        
        kwargs = dict()
        popen = subprocess.Popen(command, env=env, **kwargs)
        popen.wait()

    def loop(self):
        while True:
            job = self.check_queue()
            if not job:
                time.sleep(20)
                continue
            self.run_job(job)
            time.sleep(5)


def run_agent(spec):
    if not spec or len(spec) < 1:
        click.echo("ERROR: Specify agent spec in the form: 'entity/project' or 'entity/project/queue'")
        sys.exit(1)
    spec = spec[0]
    print("Super agent spec: %s" % spec)

    agent = Agent(spec)

    agent.loop()
