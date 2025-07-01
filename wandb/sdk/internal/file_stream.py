import functools
import itertools
import json
import logging
import os
import queue
import random
import sys
import threading
import time
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    NamedTuple,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
)

if TYPE_CHECKING:
    from typing import TypedDict

    class ProcessedChunk(TypedDict):
        offset: int
        content: List[str]

    class ProcessedBinaryChunk(TypedDict):
        offset: int
        content: str
        encoding: str


import requests

import wandb
from wandb import util
from wandb.sdk.internal import internal_api

from ..lib import file_stream_utils

logger = logging.getLogger(__name__)


class Chunk(NamedTuple):
    filename: str
    data: str


class DefaultFilePolicy:
    def __init__(self, start_chunk_id: int = 0) -> None:
        self._chunk_id = start_chunk_id
        self.has_debug_log = False

    def process_chunks(
        self, chunks: List[Chunk]
    ) -> Union[bool, "ProcessedChunk", "ProcessedBinaryChunk", List["ProcessedChunk"]]:
        chunk_id = self._chunk_id
        self._chunk_id += len(chunks)
        return {"offset": chunk_id, "content": [c.data for c in chunks]}

    # TODO: this is very inefficient, this is meant for temporary debugging and will be removed in future releases
    def _debug_log(self, data: Any):
        if self.has_debug_log or not os.environ.get("WANDB_DEBUG_FILESTREAM_LOG"):
            return

        loaded = json.loads(data)
        if not isinstance(loaded, dict):
            return

        # get key size and convert to MB
        key_sizes = [(k, len(json.dumps(v))) for k, v in loaded.items()]
        key_msg = [f"{k}: {v / 1048576:.5f} MB" for k, v in key_sizes]
        wandb.termerror(f"Step: {loaded['_step']} | {key_msg}", repeat=False)
        self.has_debug_log = True


class JsonlFilePolicy(DefaultFilePolicy):
    def process_chunks(self, chunks: List[Chunk]) -> "ProcessedChunk":
        chunk_id = self._chunk_id
        # TODO: chunk_id is getting reset on each request...
        self._chunk_id += len(chunks)
        chunk_data = []
        for chunk in chunks:
            if len(chunk.data) > util.MAX_LINE_BYTES:
                msg = f"Metric data exceeds maximum size of {util.to_human_size(util.MAX_LINE_BYTES)} ({util.to_human_size(len(chunk.data))})"
                wandb.termerror(msg, repeat=False)
                wandb._sentry.message(msg, repeat=False)
                self._debug_log(chunk.data)
            else:
                chunk_data.append(chunk.data)

        return {
            "offset": chunk_id,
            "content": chunk_data,
        }


class SummaryFilePolicy(DefaultFilePolicy):
    def process_chunks(self, chunks: List[Chunk]) -> Union[bool, "ProcessedChunk"]:
        data = chunks[-1].data
        if len(data) > util.MAX_LINE_BYTES:
            msg = f"Summary data exceeds maximum size of {util.to_human_size(util.MAX_LINE_BYTES)}. Dropping it."
            wandb.termerror(msg, repeat=False)
            wandb._sentry.message(msg, repeat=False)
            self._debug_log(data)
            return False
        return {"offset": 0, "content": [data]}


class StreamCRState:
    r"""Stream state that tracks carriage returns.

    There are two streams: stdout and stderr. We create two instances for each stream.
    An instance holds state about:
        found_cr:       if a carriage return has been found in this stream.
        cr:             most recent offset (line number) where we found \r.
                        We update this offset with every progress bar update.
        last_normal:    most recent offset without a \r in this stream.
                        i.e. the most recent "normal" line.
    """

    found_cr: bool
    cr: Optional[int]
    last_normal: Optional[int]

    def __init__(self) -> None:
        self.found_cr = False
        self.cr = None
        self.last_normal = None


class CRDedupeFilePolicy(DefaultFilePolicy):
    r"""File stream policy for removing carriage-return erased characters.

    This is what a terminal does. We use it for console output to reduce the amount of
    data we need to send over the network (eg. for progress bars), while preserving the
    output's appearance in the web app.

    CR stands for "carriage return", for the character \r. It tells the terminal to move
    the cursor back to the start of the current line. Progress bars (like tqdm) use \r
    repeatedly to overwrite a line with newer updates. This gives the illusion of the
    progress bar filling up in real-time.
    """

    def __init__(self, start_chunk_id: int = 0) -> None:
        super().__init__(start_chunk_id=start_chunk_id)
        self._prev_chunk = None

        self.global_offset = 0
        # cr refers to carriage return \r
        self.stderr = StreamCRState()
        self.stdout = StreamCRState()

    @staticmethod
    def get_consecutive_offsets(console: Dict[int, str]) -> List[List[int]]:
        """Compress consecutive line numbers into an interval.

        Args:
            console: Dict[int, str] which maps offsets (line numbers) to lines of text.
            It represents a mini version of our console dashboard on the UI.

        Returns:
            A list of intervals (we compress consecutive line numbers into an interval).

        Example:
            >>> console = {2: "", 3: "", 4: "", 5: "", 10: "", 11: "", 20: ""}
            >>> get_consecutive_offsets(console)
            [(2, 5), (10, 11), (20, 20)]
        """
        offsets = sorted(list(console.keys()))
        intervals: List = []
        for i, num in enumerate(offsets):
            if i == 0:
                intervals.append([num, num])
                continue
            largest = intervals[-1][1]
            if num == largest + 1:
                intervals[-1][1] = num
            else:
                intervals.append([num, num])
        return intervals

    @staticmethod
    def split_chunk(chunk: Chunk) -> Tuple[str, str]:
        r"""Split chunks.

        Args:
            chunk: object with two fields: filename (str) & data (str)
            `chunk.data` is a str containing the lines we want. It usually contains \n or \r or both.
            `chunk.data` has two possible formats (for the two streams - stdout and stderr):
                - "2020-08-25T20:38:36.895321 this is my line of text\nsecond line\n"
                - "ERROR 2020-08-25T20:38:36.895321 this is my line of text\nsecond line\nthird\n".

                Here's another example with a carriage return \r.
                - "ERROR 2020-08-25T20:38:36.895321 \r progress bar\n"

        Returns:
            A 2-tuple of strings.
            First str is prefix, either "ERROR {timestamp} " or "{timestamp} ".
            Second str is the rest of the string.

        Example:
            >>> chunk = Chunk(
            ...     filename="output.log",
            ...     data="ERROR 2020-08-25T20:38 this is my line of text\n",
            ... )
            >>> split_chunk(chunk)
            ("ERROR 2020-08-25T20:38 ", "this is my line of text\n")
        """
        prefix = ""
        token, rest = chunk.data.split(" ", 1)
        if token == "ERROR":
            prefix += token + " "
            token, rest = rest.split(" ", 1)
        prefix += token + " "
        return prefix, rest

    def process_chunks(self, chunks: List[Chunk]) -> List["ProcessedChunk"]:
        r"""Process chunks.

        Args:
            chunks: List of Chunk objects. See description of chunk above in `split_chunk(...)`.

        Returns:
            List[Dict]. Each dict in the list contains two keys: an `offset` which holds the line number
            and `content` which maps to a list of consecutive lines starting from that offset.
            `offset` here means global line number in our console on the UI.

        Example:
            >>> chunks = [
                Chunk("output.log", "ERROR 2020-08-25T20:38 this is my line of text\nboom\n"),
                Chunk("output.log", "2020-08-25T20:38 this is test\n"),
            ]
            >>> process_chunks(chunks)
            [
                {"offset": 0, "content": [
                    "ERROR 2020-08-25T20:38 this is my line of text\n",
                    "ERROR 2020-08-25T20:38 boom\n",
                    "2020-08-25T20:38 this is test\n"
                    ]
                }
            ]
        """
        # Dict[int->str], each offset (line number) mapped to a line.
        # Represents a mini-version of our console pane on the UI.
        console = {}
        sep = os.linesep

        for c in chunks:
            prefix, logs_str = self.split_chunk(c)
            logs = logs_str.split(sep)

            for line in logs:
                stream = self.stderr if prefix.startswith("ERROR ") else self.stdout
                if line.startswith("\r"):
                    # line starting with \r will always overwrite a previous offset.
                    offset: int = (
                        stream.cr
                        if (stream.found_cr and stream.cr is not None)
                        else (stream.last_normal or 0)
                    )
                    stream.cr = offset
                    stream.found_cr = True
                    console[offset] = prefix + line[1:] + "\n"

                    # Usually logs_str = "\r progress bar\n" for progress bar updates.
                    # If instead logs_str = "\r progress bar\n text\n text\n",
                    # treat this as the end of a progress bar and reset accordingly.
                    if (
                        logs_str.count(sep) > 1
                        and logs_str.replace(sep, "").count("\r") == 1
                    ):
                        stream.found_cr = False

                elif line:
                    console[self.global_offset] = prefix + line + "\n"
                    stream.last_normal = self.global_offset
                    self.global_offset += 1

        intervals = self.get_consecutive_offsets(console)
        ret = []
        for a, b in intervals:
            processed_chunk: ProcessedChunk = {
                "offset": self._chunk_id + a,
                "content": [console[i] for i in range(a, b + 1)],
            }
            ret.append(processed_chunk)
        return ret


class FileStreamApi:
    """Pushes chunks of files to our streaming endpoint.

    This class is used as a singleton. It has a thread that serializes access to
    the streaming endpoint and performs rate-limiting and batching.

    TODO: Differentiate between binary/text encoding.
    """

    class Finish(NamedTuple):
        exitcode: int

    class Preempting(NamedTuple):
        pass

    class PushSuccess(NamedTuple):
        artifact_id: str
        save_name: str

    MAX_ITEMS_PER_PUSH = 10000

    def __init__(
        self,
        api: "internal_api.Api",
        run_id: str,
        start_time: float,
        timeout: float = 0,
        settings: Optional[dict] = None,
    ) -> None:
        settings = settings or dict()
        # NOTE: exc_info is set in thread_except_body context and readable by calling threads
        self._exc_info: Optional[
            Union[
                Tuple[Type[BaseException], BaseException, TracebackType],
                Tuple[None, None, None],
            ]
        ] = None
        self._settings = settings
        self._api = api
        self._run_id = run_id
        self._start_time = start_time
        self._client = requests.Session()
        timeout = timeout or 0
        if timeout > 0:
            self._client.post = functools.partial(self._client.post, timeout=timeout)  # type: ignore[method-assign]
        self._client.auth = api.client.transport.session.auth
        self._client.headers.update(api.client.transport.headers or {})
        self._client.cookies.update(api.client.transport.cookies or {})  # type: ignore[no-untyped-call]
        self._client.proxies.update(api.client.transport.session.proxies or {})
        self._file_policies: Dict[str, DefaultFilePolicy] = {}
        self._dropped_chunks: int = 0
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._thread_except_body)
        # It seems we need to make this a daemon thread to get sync.py's atexit handler to run, which
        # cleans this thread up.
        self._thread.name = "FileStreamThread"
        self._thread.daemon = True
        self._init_endpoint()

    def _init_endpoint(self) -> None:
        settings = self._api.settings()
        settings.update(self._settings)
        self._endpoint = "{base}/files/{entity}/{project}/{run}/file_stream".format(
            base=settings["base_url"],
            entity=settings["entity"],
            project=settings["project"],
            run=self._run_id,
        )

    def start(self) -> None:
        self._init_endpoint()
        self._thread.start()

    def set_default_file_policy(
        self, filename: str, file_policy: "DefaultFilePolicy"
    ) -> None:
        """Set an upload policy for a file unless one has already been set."""
        if filename not in self._file_policies:
            self._file_policies[filename] = file_policy

    def set_file_policy(self, filename: str, file_policy: "DefaultFilePolicy") -> None:
        self._file_policies[filename] = file_policy

    @property
    def heartbeat_seconds(self) -> Union[int, float]:
        # Defaults to 30
        heartbeat_seconds: Union[int, float] = self._api.dynamic_settings[
            "heartbeat_seconds"
        ]
        return heartbeat_seconds

    def rate_limit_seconds(self) -> Union[int, float]:
        run_time = time.time() - self._start_time
        if run_time < 60:
            return max(1.0, self.heartbeat_seconds / 15)
        elif run_time < 300:
            return max(2.5, self.heartbeat_seconds / 3)
        else:
            return max(5.0, self.heartbeat_seconds)

    def _read_queue(self) -> List:
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

    def _thread_body(self) -> None:
        posted_data_time = time.time()
        posted_anything_time = time.time()
        ready_chunks = []
        uploaded: Set[str] = set()
        finished: Optional[FileStreamApi.Finish] = None
        while finished is None:
            items = self._read_queue()
            for item in items:
                if isinstance(item, self.Finish):
                    finished = item
                elif isinstance(item, self.Preempting):
                    request_with_retry(
                        self._client.post,
                        self._endpoint,
                        json={
                            "complete": False,
                            "preempting": True,
                            "dropped": self._dropped_chunks,
                            "uploaded": list(uploaded),
                        },
                    )
                    uploaded = set()
                elif isinstance(item, self.PushSuccess):
                    uploaded.add(item.save_name)
                else:
                    # item is Chunk
                    ready_chunks.append(item)

            cur_time = time.time()

            if ready_chunks and (
                finished or cur_time - posted_data_time > self.rate_limit_seconds()
            ):
                posted_data_time = cur_time
                posted_anything_time = cur_time
                success = self._send(ready_chunks, uploaded=uploaded)
                ready_chunks = []
                if success:
                    uploaded = set()

            # If there aren't ready chunks or uploaded files, we still want to
            # send regular heartbeats so the backend doesn't erroneously mark this
            # run as crashed.
            if cur_time - posted_anything_time > self.heartbeat_seconds:
                posted_anything_time = cur_time

                # If we encountered an error trying to publish the
                # list of uploaded files, don't reset the `uploaded`
                # list. Retry publishing the list on the next attempt.
                if not isinstance(
                    request_with_retry(
                        self._client.post,
                        self._endpoint,
                        json={
                            "complete": False,
                            "failed": False,
                            "dropped": self._dropped_chunks,
                            "uploaded": list(uploaded),
                        },
                    ),
                    Exception,
                ):
                    uploaded = set()

        # post the final close message. (item is self.Finish instance now)
        request_with_retry(
            self._client.post,
            self._endpoint,
            json={
                "complete": True,
                "exitcode": int(finished.exitcode),
                "dropped": self._dropped_chunks,
                "uploaded": list(uploaded),
            },
        )

    def _thread_except_body(self) -> None:
        # TODO: Consolidate with internal_util.ExceptionThread
        try:
            self._thread_body()
        except Exception:
            exc_info = sys.exc_info()
            self._exc_info = exc_info
            logger.exception("generic exception in filestream thread")
            wandb._sentry.exception(exc_info)
            raise

    def _handle_response(self, response: Union[Exception, "requests.Response"]) -> None:
        """Log dropped chunks and updates dynamic settings."""
        if isinstance(response, Exception):
            wandb.termerror(
                "Dropped streaming file chunk (see wandb/debug-internal.log)"
            )
            logger.exception(f"dropped chunk {response}")
            self._dropped_chunks += 1
        else:
            parsed: Optional[dict] = None
            try:
                parsed = response.json()
            except Exception:
                pass
            if isinstance(parsed, dict):
                limits = parsed.get("limits")
                if isinstance(limits, dict):
                    self._api.dynamic_settings.update(limits)

    def _send(self, chunks: List[Chunk], uploaded: Optional[Set[str]] = None) -> bool:
        uploaded_list = list(uploaded or [])
        # create files dict. dict of <filename: chunks> pairs where chunks are a list of
        # [chunk_id, chunk_data] tuples (as lists since this will be json).
        files = {}
        # Groupby needs group keys to be consecutive, so sort first.
        chunks.sort(key=lambda c: c.filename)
        for filename, file_chunks in itertools.groupby(chunks, lambda c: c.filename):
            file_chunks_list = list(file_chunks)  # groupby returns iterator
            # Specific file policies are set by internal/sender.py
            self.set_default_file_policy(filename, DefaultFilePolicy())
            files[filename] = self._file_policies[filename].process_chunks(
                file_chunks_list
            )
            if not files[filename]:
                del files[filename]

        for fs in file_stream_utils.split_files(files, max_bytes=util.MAX_LINE_BYTES):
            self._handle_response(
                request_with_retry(
                    self._client.post,
                    self._endpoint,
                    json={"files": fs, "dropped": self._dropped_chunks},
                    retry_callback=self._api.retry_callback,
                )
            )

        if uploaded_list:
            if isinstance(
                request_with_retry(
                    self._client.post,
                    self._endpoint,
                    json={
                        "complete": False,
                        "failed": False,
                        "dropped": self._dropped_chunks,
                        "uploaded": uploaded_list,
                    },
                ),
                Exception,
            ):
                return False
        return True

    def stream_file(self, path: str) -> None:
        name = path.split("/")[-1]
        with open(path) as f:
            self._send([Chunk(name, line) for line in f])

    def enqueue_preempting(self) -> None:
        self._queue.put(self.Preempting())

    def push(self, filename: str, data: str) -> None:
        """Push a chunk of a file to the streaming endpoint.

        Args:
            filename: Name of file to append to.
            data: Text to append to the file.
        """
        self._queue.put(Chunk(filename, data))

    def push_success(self, artifact_id: str, save_name: str) -> None:
        """Notification that a file upload has been successfully completed.

        Args:
            artifact_id: ID of artifact
            save_name: saved name of the uploaded file
        """
        self._queue.put(self.PushSuccess(artifact_id, save_name))

    def finish(self, exitcode: int) -> None:
        """Clean up.

        Anything pushed after finish will be dropped.

        Args:
            exitcode: The exitcode of the watched process.
        """
        logger.info("file stream finish called")
        self._queue.put(self.Finish(exitcode))
        # TODO(jhr): join on a thread which exited with an exception is a noop, clean up this path
        self._thread.join()
        logger.info("file stream finish is done")
        if self._exc_info:
            logger.error("FileStream exception", exc_info=self._exc_info)
            # re-raising the original exception, will get re-caught in internal.py for the sender thread
            if self._exc_info[1] is not None:
                raise self._exc_info[1].with_traceback(self._exc_info[2])


MAX_SLEEP_SECONDS = 60 * 5


def request_with_retry(
    func: Callable,
    *args: Any,
    **kwargs: Any,
) -> Union["requests.Response", "requests.RequestException"]:
    """Perform a requests http call, retrying with exponential backoff.

    Args:
        func:        An http-requesting function to call, like requests.post
        max_retries: Maximum retries before giving up.
                     By default, we retry 30 times in ~2 hours before dropping the chunk
        *args:       passed through to func
        **kwargs:    passed through to func
    """
    max_retries: int = kwargs.pop("max_retries", 30)
    retry_callback: Optional[Callable] = kwargs.pop("retry_callback", None)
    sleep = 2
    retry_count = 0
    while True:
        try:
            response: requests.Response = func(*args, **kwargs)
            response.raise_for_status()
            return response
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
        ) as e:
            if isinstance(e, requests.exceptions.HTTPError):
                # Non-retriable HTTP errors.
                #
                # We retry 500s just to be cautious, and because the back end
                # returns them when there are infrastructure issues. If retrying
                # some request winds up being problematic, we'll change the
                # back end to indicate that it shouldn't be retried.
                if e.response is not None and e.response.status_code in {
                    400,
                    403,
                    404,
                    409,
                }:
                    return e

            if retry_count == max_retries:
                return e
            retry_count += 1
            delay = sleep + random.random() * 0.25 * sleep
            if isinstance(e, requests.exceptions.HTTPError) and (
                e.response is not None and e.response.status_code == 429
            ):
                err_str = (
                    f"Filestream rate limit exceeded, retrying in {delay:.1f} seconds. "
                )
                if retry_callback:
                    retry_callback(e.response.status_code, err_str)
                logger.info(err_str)
            else:
                logger.warning(
                    "requests_with_retry encountered retryable exception: %s. func: %s, args: %s, kwargs: %s",
                    e,
                    func,
                    args,
                    kwargs,
                )
            time.sleep(delay)
            sleep *= 2
            if sleep > MAX_SLEEP_SECONDS:
                sleep = MAX_SLEEP_SECONDS
        except requests.exceptions.RequestException as e:
            error_message = "unknown error"
            try:
                error_message = response.json()["error"]  # todo: clean this up
            except Exception:
                pass
            logger.exception(f"requests_with_retry error: {error_message}")
            return e
