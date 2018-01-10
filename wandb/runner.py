import copy
import multiprocessing
import os
from six.moves import queue
import signal
import sys
import time

from wandb import wandb_run
from wandb import util
from wandb import sync
from wandb import wandb_api
from wandb import streaming_log


class RunnerError(Exception):
    pass


class SingleRun(multiprocessing.Process):
    def __init__(self, api, program, args, id, dir, configs, message, show, show_output, sweep_id, **kwargs):
        super(SingleRun, self).__init__(**kwargs)
        self._api = api
        self._program = program
        self._args = args
        self._id = id
        self._dir = dir
        self._configs = configs
        self._message = message
        self._show = show
        self._result_queue = multiprocessing.Queue()
        self._show_output = show_output
        self._sweep_id = sweep_id
        self._stop_queue = multiprocessing.Queue()

    def run(self):
        # The process

        if self._id is None:
            self._id = wandb_run.generate_id()
        if self._dir is None:
            self._dir = wandb_run.run_dir_path(self._id, dry=False)
            util.mkdir_exists_ok(self._dir)
        if self._message:
            open(os.path.join(dir, 'description.md'),
                 'w').write('%s\n' % self._message)

        # setup child environment
        env = copy.copy(os.environ)
        # tell child python interpreters we accept utf-8
        # TODO(adrian): is there a language-agnostic way of doing this?
        env['PYTHONIOENCODING'] = 'UTF-8'
        env['WANDB_MODE'] = 'run'
        env['WANDB_RUN_ID'] = self._id
        env['WANDB_RUN_DIR'] = self._dir
        if self._configs:
            env['WANDB_CONFIG_PATHS'] = self._configs
        if self._show:
            env['WANDB_SHOW_RUN'] = '1'
        if self._sweep_id:
            env['WANDB_SWEEP_ID'] = self._sweep_id
        #env['WANDB_INITED'] = '1'

        # if self._api.api_key is None:
        #    raise wandb_api.Error(
        #        "No API key found, run `wandb login` or set WANDB_API_KEY")
        #run = wandb_run.Run(self._id, self._dir, None)
        # self._api.set_current_run_id(run.id)
        #syncer = sync.Sync(self._api, 'train', run, config=run.config)
        #syncer.watch(files='*', show_run=self._show)

        # stdout_stream = streaming_log.TextStreamPusher(
        #    self._api.get_file_stream_api(), 'output.log', prepend_timestamp=True)
        # stderr_stream = streaming_log.TextStreamPusher(
        #    self._api.get_file_stream_api(), 'output.log', line_prepend='ERROR',
        #    prepend_timestamp=True)

        command = [self._program] + list(self._args)
        runner = util.find_runner(self._program)
        if runner:
            command = runner.split() + command
        proc = util.SafeSubprocess(command, read_output=self._show_output)
        result = {'type': 'start', 'run_id': self._id}
        try:
            proc.run()
        except (OSError, IOError):
            result['error'] = 'Could not find program: %s' % self._program
        self._result_queue.put(result)
        if result.get('error'):
            return

        # ignore SIGINT (ctrl-c), the child process will handle, and we'll
        # exit when the child process does.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        exitcode = None
        while True:
            time.sleep(0.1)
            try:
                self._stop_queue.get_nowait()
                print('Sending SIGTERM')
                proc.terminate()
            except queue.Empty:
                pass
            exitcode, stdout, stderr = proc.poll()
            for line in stdout:
                # stdout_stream.write(line)
                if self._show_output:
                    sys.stdout.write(line)
            for line in stderr:
                # stderr_stream.write(line)
                if self._show_output:
                    sys.stderr.write(line)
            if exitcode is not None:
                break
        # stdout_stream.close()
        # stderr_stream.close()
        # syncer.stop()

        self._result_queue.put({'type': 'finish', 'exitcode': exitcode})

    def next_event(self):
        return self._result_queue.get()

    def is_running(self):
        try:
            finish_event = self._result_queue.get_nowait()
            return False
        except queue.Empty:
            return True

    def launch(self):
        self.start()

    def term(self):
        self._stop_queue.put(True)


class Runner(object):
    def __init__(self, api):
        self._api = api
        self._runs = {}

    def run(self, program, args, id=None, dir=None,
            configs=None, message=None, show=None, show_output=True, sweep_id=None):
        print('Run: %s %s' % (program, args))
        run = SingleRun(self._api, program, args, id,
                        dir, configs, message, show, show_output,
                        sweep_id)
        run.launch()
        start_event = run.next_event()
        assert(start_event['type'] == 'start')
        if 'error' in start_event:
            raise RunnerError(start_event['error'])
        run_id = start_event['run_id']
        self._runs[run_id] = run
        return run_id

    def stop(self, run_id):
        print('Stop: %s' % run_id)
        if run_id in self._runs:
            self._runs[run_id].term()
        else:
            print('Run %s not running' % run_id)

    def running_runs(self):
        remove_runs = []
        for run_id, run in self._runs.items():
            if not run.is_running():
                remove_runs.append(run_id)
        for run in remove_runs:
            self._runs.pop(run)
        return list(self._runs.keys())
