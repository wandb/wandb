import sys
import click

import time

def query_queue():
    pass


class Agent(object):

    def __init__(self, spec):
        self._spec = spec

    def check_queue(self):
        return

    def run_job(self, job):
        print("agent: got job", job)
        pass

    def loop(self):
        while True:
            job = self.check_queue()
            if not job:
                time.sleep(10)
            self.run_job(job)
            time.sleep(5)


def run_agent(spec):
    if not spec or len(spec) < 1:
        click.echo("ERROR: Specify agent spec in the form: 'entiy/project' or 'entity/project/queue'")
        sys.exit(1)
    spec = spec[0]
    print("Super agent spec: %s" % spec)

    agent = Agent(spec)

    agent.loop()
