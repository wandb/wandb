import base64
import binascii
import collections
import logging
import threading
import requests
import time
import wandb
import itertools
from six.moves import queue
from wandb import util
from wandb import env

MAX_LINE_SIZE = 4*1024*1024 - 100*1024  # imposed by back end

logger = logging.getLogger(__name__)

Chunk = collections.namedtuple('Chunk', ('filename', 'data'))


class DefaultFilePolicy(object):
    def __init__(self, start_chunk_id=0):
        self._chunk_id = start_chunk_id

    def process_chunks(self, chunks):
        chunk_id = self._chunk_id
        self._chunk_id += len(chunks)
        return {
            'offset': chunk_id,
            'content': [c.data for c in chunks]
        }


class JsonlFilePolicy(object):
    def __init__(self, start_chunk_id=0):
        self._chunk_id = start_chunk_id

    def process_chunks(self, chunks):
        chunk_id = self._chunk_id
        self._chunk_id += len(chunks)
        chunk_data = []
        for chunk in chunks:
            if len(chunk.data) > MAX_LINE_SIZE:
                msg = 'Metric data exceeds maximum size of {} bytes. Dropping it.'.format(MAX_LINE_SIZE)
                wandb.termerror(msg, repeat=False)
                util.sentry_message(msg)
            else:
                chunk_data.append(chunk.data)

        return {
            'offset': chunk_id,
            'content': chunk_data,
        }


class SummaryFilePolicy(object):
    def process_chunks(self, chunks):
        data = chunks[-1].data
        if len(data) > MAX_LINE_SIZE:
            msg = 'Summary data exceeds maximum size of {} bytes. Dropping it.'.format(MAX_LINE_SIZE)
            wandb.termerror(msg, repeat=False)
            util.sentry_message(msg)
            return False
        return {
            'offset': 0, 'content': [data]
        }


class CRDedupeFilePolicy(object):
    """File stream policy that removes characters that would be erased by
    carriage returns.

    This is what a terminal does. We use it for console output to reduce the
    amount of data we need to send over the network (eg. for progress bars),
    while preserving the output's appearance in the web app.
    """

    def __init__(self, start_chunk_id=0):
        self._chunk_id = start_chunk_id

    def process_chunks(self, chunks):
        content = []
        for line in [c.data for c in chunks]:
            if content and content[-1].endswith('\r'):
                content[-1] = line
            else:
                content.append(line)
        chunk_id = self._chunk_id
        self._chunk_id += len(content)
        if content and content[-1].endswith('\r'):
            self._chunk_id -= 1
        return {
            'offset': chunk_id,
            'content': content
        }


class BinaryFilePolicy(object):
    def __init__(self):
        self._offset = 0

    def process_chunks(self, chunks):
        data = b''.join([c.data for c in chunks])
        enc = base64.b64encode(data).decode('ascii')
        offset = self._offset
        self._offset += len(data)
        return {
            'offset': self._offset,
            'content': enc,
            'encoding': 'base64'
        }


class FileStreamApi(object):
    """Pushes chunks of files to our streaming endpoint.

    This class is used as a singleton. It has a thread that serializes access to
    the streaming endpoint and performs rate-limiting and batching.

    TODO: Differentiate between binary/text encoding.
    """
    Finish = collections.namedtuple('Finish', ('exitcode'))

    HTTP_TIMEOUT = env.get_http_timeout(10)
    MAX_ITEMS_PER_PUSH = 10000

    def __init__(self, api, run_id):
        self._api = api
        self._run_id = run_id
        self._client = requests.Session()
        self._client.auth = ('api', api.api_key)
        self._client.timeout = self.HTTP_TIMEOUT
        self._client.headers.update({
            'User-Agent': api.user_agent,
            'X-WANDB-USERNAME': env.get_username(),
            'X-WANDB-USER-EMAIL': env.get_user_email()
        })
        self._file_policies = {}
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._thread_body)
        # It seems we need to make this a daemon thread to get sync.py's atexit handler to run, which
        # cleans this thread up.
        self._thread.daemon = True
        self._init_endpoint()

    def _init_endpoint(self):
        settings = self._api.settings()
        self._endpoint = "{base}/files/{entity}/{project}/{run}/file_stream".format(
            base=settings['base_url'],
            entity=settings['entity'],
            project=settings['project'],
            run=self._run_id)

    def start(self):
        self._init_endpoint()
        self._thread.start()

    def set_default_file_policy(self, filename, file_policy):
        """Set an upload policy for a file unless one has already been set.
        """
        if filename not in self._file_policies:
            self._file_policies[filename] = file_policy

    def set_file_policy(self, filename, file_policy):
        self._file_policies[filename] = file_policy

    @property
    def heartbeat_seconds(self):
        # Defaults to 30
        return self._api.dynamic_settings["heartbeat_seconds"]

    def rate_limit_seconds(self):
        run_time = time.time() - wandb.START_TIME
        if run_time < 60:
            return max(1, self.heartbeat_seconds / 15)
        elif run_time < 300:
            return max(2.5, self.heartbeat_seconds / 3)
        else:
            return max(5, self.heartbeat_seconds)

    def _read_queue(self):
        # called from the push thread (_thread_body), this does an initial read
        # that'll block for up to rate_limit_seconds. Then it tries to read
        # as much out of the queue as it can. We do this because the http post
        # to the server happens within _thread_body, and can take longer than
        # our rate limit. So next time we get a chance to read the queue we want
        # read all the stuff that queue'd up since last time.
        #
        # If we have more than MAX_ITEMS_PER_PUSH in the queue then the push thread
        # will get behind and data will buffer up in the queue.
        return util.read_many_from_queue(
            self._queue, self.MAX_ITEMS_PER_PUSH, self.rate_limit_seconds())

    def _thread_body(self):
        posted_data_time = time.time()
        posted_anything_time = time.time()
        ready_chunks = []
        finished = None
        while finished is None:
            items = self._read_queue()
            for item in items:
                if isinstance(item, self.Finish):
                    finished = item
                else:
                    # item is Chunk
                    ready_chunks.append(item)

            cur_time = time.time()

            if ready_chunks and (finished or cur_time - posted_data_time > self.rate_limit_seconds()):
                posted_data_time = cur_time
                posted_anything_time = cur_time
                self._send(ready_chunks)
                ready_chunks = []

            if cur_time - posted_anything_time > self.heartbeat_seconds:
                posted_anything_time = cur_time
                self._handle_response(util.request_with_retry(self._client.post,
                                                              self._endpoint, json={'complete': False, 'failed': False}))
        # post the final close message. (item is self.Finish instance now)
        util.request_with_retry(self._client.post,
                                self._endpoint, json={'complete': True, 'exitcode': int(finished.exitcode)})

    def _handle_response(self, response):
        """Logs dropped chunks and updates dynamic settings"""
        if isinstance(response, Exception):
            raise response
            wandb.termerror('Droppped streaming file chunk (see wandb/debug.log)')
            logging.error("dropped chunk %s" % response)
        elif response.json().get("limits"):
            parsed = response.json()
            self._api.dynamic_settings.update(parsed["limits"])

    def _send(self, chunks):
        # create files dict. dict of <filename: chunks> pairs where chunks is a list of
        # [chunk_id, chunk_data] tuples (as lists since this will be json).
        files = {}
        # Groupby needs group keys to be consecutive, so sort first.
        chunks.sort(key=lambda c: c.filename)
        for filename, file_chunks in itertools.groupby(chunks, lambda c: c.filename):
            file_chunks = list(file_chunks)  # groupby returns iterator
            self.set_default_file_policy(filename, DefaultFilePolicy())
            files[filename] = self._file_policies[filename].process_chunks(
                file_chunks)
            if not files[filename]:
                del files[filename]

        self._handle_response(util.request_with_retry(
            self._client.post, self._endpoint, json={'files': files}))

    def stream_file(self, path):
        name = path.split("/")[-1]
        with open(path) as f:
            self._send([Chunk(name, line) for line in f])

    def push(self, filename, data):
        """Push a chunk of a file to the streaming endpoint.

        Args:
            filename: Name of file that this is a chunk of.
            chunk_id: TODO: change to 'offset'
            chunk: File data.
        """
        self._queue.put(Chunk(filename, data))

    def finish(self, exitcode):
        """Cleans up.

        Anything pushed after finish will be dropped.

        Args:
            exitcode: The exitcode of the watched process.
        """
        self._queue.put(self.Finish(exitcode))
        self._thread.join()
