import base64
import binascii
import collections
import itertools
import logging
import os
import sys
import requests
import threading
import time

import wandb
from wandb import util
from wandb import env

from six.moves import queue

from ..lib import file_stream_utils


logger = logging.getLogger(__name__)

Chunk = collections.namedtuple("Chunk", ("filename", "data"))


class DefaultFilePolicy(object):
    def __init__(self, start_chunk_id=0):
        self._chunk_id = start_chunk_id

    def process_chunks(self, chunks):
        chunk_id = self._chunk_id
        self._chunk_id += len(chunks)
        return {"offset": chunk_id, "content": [c.data for c in chunks]}


class JsonlFilePolicy(DefaultFilePolicy):
    def process_chunks(self, chunks):
        chunk_id = self._chunk_id
        # TODO: chunk_id is getting reset on each request...
        self._chunk_id += len(chunks)
        chunk_data = []
        for chunk in chunks:
            if len(chunk.data) > util.MAX_LINE_SIZE:
                msg = "Metric data exceeds maximum size of {} ({})".format(
                    util.to_human_size(util.MAX_LINE_SIZE),
                    util.to_human_size(len(chunk.data)),
                )
                wandb.termerror(msg, repeat=False)
                util.sentry_message(msg)
            else:
                chunk_data.append(chunk.data)

        return {
            "offset": chunk_id,
            "content": chunk_data,
        }


class SummaryFilePolicy(DefaultFilePolicy):
    def process_chunks(self, chunks):
        data = chunks[-1].data
        if len(data) > util.MAX_LINE_SIZE:
            msg = "Summary data exceeds maximum size of {}. Dropping it.".format(
                util.to_human_size(util.MAX_LINE_SIZE)
            )
            wandb.termerror(msg, repeat=False)
            util.sentry_message(msg)
            return False
        return {"offset": 0, "content": [data]}


class CRDedupeFilePolicy(DefaultFilePolicy):
    """File stream policy that removes characters that would be erased by
    carriage returns.

    This is what a terminal does. We use it for console output to reduce the
    amount of data we need to send over the network (eg. for progress bars),
    while preserving the output's appearance in the web app.
    """

    def __init__(self, start_chunk_id=0):
        super(CRDedupeFilePolicy, self).__init__(start_chunk_id=start_chunk_id)
        self._prev_chunk = None

    def process_chunks(self, chunks):
        ret = []
        flag = bool(self._prev_chunk)
        chunk_id = self._chunk_id
        for c in chunks:
            # Line has two possible formats:
            # 1) "2020-08-25T20:38:36.895321 this is my line of text"
            # 2) "ERROR 2020-08-25T20:38:36.895321 this is my line of text"
            prefix = ""
            token, rest = c.data.split(" ", 1)
            is_err = False
            if token == "ERROR":
                is_err = True
                prefix += token + " "
                token, rest = rest.split(" ", 1)
            prefix += token + " "

            lines = rest.split(os.linesep)
            for line in lines:
                if line.startswith("\r"):
                    found = False
                    for i in range(len(ret) - 1, -1, -1):
                        if ret[i].startswith("ERROR ") == is_err:
                            ret[i] = prefix + line[1:] + "\n"
                            found = True
                            break
                    if not found:
                        if flag:
                            flag = False
                            prev_ret = self._prev_chunk["content"]
                            for i in range(len(prev_ret) - 1, -1, -1):
                                if prev_ret[i].startswith("ERROR ") == is_err:
                                    prev_ret[i] = prefix + line[1:] + "\n"
                                    found = True
                                    break
                            if found:
                                chunk_id = self._prev_chunk["offset"]
                                ret = prev_ret + ret
                            else:
                                ret.append(prefix + line[1:] + "\n")
                        else:
                            ret.append(prefix + line[1:] + "\n")
                elif line:
                    ret.append(prefix + line + "\n")
        self._chunk_id = chunk_id + len(ret)
        ret = {"offset": chunk_id, "content": ret}
        self._prev_chunk = ret
        return ret


class BinaryFilePolicy(DefaultFilePolicy):
    def process_chunks(self, chunks):
        data = b"".join([c.data for c in chunks])
        enc = base64.b64encode(data).decode("ascii")
        offset = self._offset
        self._offset += len(data)
        return {"offset": self._offset, "content": enc, "encoding": "base64"}


class FileStreamApi(object):
    """Pushes chunks of files to our streaming endpoint.

    This class is used as a singleton. It has a thread that serializes access to
    the streaming endpoint and performs rate-limiting and batching.

    TODO: Differentiate between binary/text encoding.
    """

    Finish = collections.namedtuple("Finish", ("exitcode"))

    HTTP_TIMEOUT = env.get_http_timeout(10)
    MAX_ITEMS_PER_PUSH = 10000

    def __init__(self, api, run_id, start_time, settings=None):
        if settings is None:
            settings = dict()
        self._settings = settings
        self._api = api
        self._run_id = run_id
        self._start_time = start_time
        self._client = requests.Session()
        self._client.auth = ("api", api.api_key)
        self._client.timeout = self.HTTP_TIMEOUT
        self._client.headers.update(
            {
                "User-Agent": api.user_agent,
                "X-WANDB-USERNAME": env.get_username(),
                "X-WANDB-USER-EMAIL": env.get_user_email(),
            }
        )
        self._file_policies = {}
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._thread_body)
        # It seems we need to make this a daemon thread to get sync.py's atexit handler to run, which
        # cleans this thread up.
        self._thread.daemon = True
        self._init_endpoint()

    def _init_endpoint(self):
        settings = self._api.settings()
        settings.update(self._settings)
        self._endpoint = "{base}/files/{entity}/{project}/{run}/file_stream".format(
            base=settings["base_url"],
            entity=settings["entity"],
            project=settings["project"],
            run=self._run_id,
        )

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
        run_time = time.time() - self._start_time
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
            self._queue, self.MAX_ITEMS_PER_PUSH, self.rate_limit_seconds()
        )

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

            if ready_chunks and (
                finished or cur_time - posted_data_time > self.rate_limit_seconds()
            ):
                posted_data_time = cur_time
                posted_anything_time = cur_time
                self._send(ready_chunks)
                ready_chunks = []

            if cur_time - posted_anything_time > self.heartbeat_seconds:
                posted_anything_time = cur_time
                self._handle_response(
                    util.request_with_retry(
                        self._client.post,
                        self._endpoint,
                        json={"complete": False, "failed": False},
                    )
                )
        # post the final close message. (item is self.Finish instance now)
        util.request_with_retry(
            self._client.post,
            self._endpoint,
            json={"complete": True, "exitcode": int(finished.exitcode)},
        )

    def _handle_response(self, response):
        """Logs dropped chunks and updates dynamic settings"""
        if isinstance(response, Exception):
            raise response
            wandb.termerror("Droppped streaming file chunk (see wandb/debug.log)")
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
            # Specific file policies are set by internal/sender.py
            self.set_default_file_policy(filename, DefaultFilePolicy())
            files[filename] = self._file_policies[filename].process_chunks(file_chunks)
            if not files[filename]:
                del files[filename]

        for fs in file_stream_utils.split_files(files, max_mb=10):
            self._handle_response(
                util.request_with_retry(
                    self._client.post, self._endpoint, json={"files": fs}
                )
            )

    def stream_file(self, path):
        name = path.split("/")[-1]
        with open(path) as f:
            self._send([Chunk(name, line) for line in f])

    def push(self, filename, data):
        """Push a chunk of a file to the streaming endpoint.

        Arguments:
            filename: Name of file that this is a chunk of.
            chunk_id: TODO: change to 'offset'
            chunk: File data.
        """
        self._queue.put(Chunk(filename, data))

    def finish(self, exitcode):
        """Cleans up.

        Anything pushed after finish will be dropped.

        Arguments:
            exitcode: The exitcode of the watched process.
        """
        self._queue.put(self.Finish(exitcode))
        self._thread.join()
