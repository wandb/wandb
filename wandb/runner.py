class Runner(object):
    def __init__(self, api):
        self._api = api

    def run(self, program, config):
        print('Run: %s %s' % (program, config))

    def stop(self, job_id):
        print('Stop: %s' % job_id)
