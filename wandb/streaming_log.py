import io
import tempfile
import time
import sys
from requests import Session
from wandb import Api
import threading
import traceback
import logging
import signal
import os

CARRIAGE_RETURN = 13
STALE_SECONDS = 2
RATE_LIMIT = 1
MAX_LINES = 5
HTTP_TIMEOUT = 3
HEARTBEAT_INTERVAL = 15

class LineBuffer(io.FileIO):
    """Writes to a tempfile while buffering lines and deduping repeated
    lines with a carriage return.  Calls push every MAX_LINES if under RATE_LIMIT,
    or atleast every STALE_SECONDS after the last line was written.
    """
    def __init__(self, path, push = lambda *args: None):
        super(LineBuffer, self).__init__(path, "w")
        self.buf = bytearray()
        self.lock = threading.RLock()
        self.line_number = 0
        self.lines = []
        self.posted = time.time()
        self.push = push

    @property
    def stale(self):
        return (len(self.lines) > 0 and 
               (time.time() - self.posted) >= STALE_SECONDS)

    @property
    def rate_limit(self):
        return time.time() - self.posted < RATE_LIMIT

    def flush(self):
        """This assumes flush is called once per line (\n, \r, or \r\n),
        io.TextIOWrapper ensures this is true"""
        super(LineBuffer, self).flush()
        if len(self.buf) == 0:
            return False
        with self.lock:
            self.line_number += 1
            lines = len(self.lines) + 1
            if(self.buf[-1] == CARRIAGE_RETURN and lines > 1
               and self.lines[-1].endswith("\r")):
                self.line_number -= 1
                self.lines.pop()
            self.lines.append(self.buf.decode("utf-8"))
            del self.buf[:]
            if (lines >= MAX_LINES and not self.rate_limit) or self.stale:
                to_push = self.lines[:]
                del self.lines[:]
                #Release the lock to allow multiple concurrent pushes
                self.lock.release()
                if self.push(to_push, self.line_number):
                    self.lock.acquire()
                    self.posted = time.time()
                else:
                    self.lock.acquire()
                    self.line_number -= 1
                    self.lines = to_push + self.lines

    def write(self, chars):
        super(LineBuffer, self).write(chars)
        with self.lock:
            self.buf.extend(chars)

class StreamingLog(io.TextIOWrapper):
    """Manages the WandB client and tempfile for log storage"""
    api = Api()
    config = api.config()
    endpoint = "{base}/{entity}/{project}/%s/logs".format(
        base=config['base_url'],
        entity=config.get("entity"),
        project=config.get("project")
    )

    def __init__(self, run, level=logging.INFO):
        self.run = run
        self.client = Session()
        self.client.auth = ("api", StreamingLog.api.api_key)
        self.client.timeout = HTTP_TIMEOUT
        self.client.headers.update({
            'User-Agent': StreamingLog.api.user_agent,
        })
        self.tempfile = tempfile.NamedTemporaryFile(mode='wb')
        self.pushed_at = time.time()
        self.pushing = 0
        self.line_buffer = LineBuffer(self.tempfile.name, push=self.push)
        #Schedule heartbeat TODO: unix only
        signal.signal(signal.SIGALRM, self.heartbeat)
        signal.setitimer(signal.ITIMER_REAL, HEARTBEAT_INTERVAL / 2)
        super(StreamingLog, self).__init__(self.line_buffer, line_buffering=True, 
                                           newline='')
    
    def heartbeat(self, *args):
        if time.time() - self.pushed_at > HEARTBEAT_INTERVAL:
            self.client.post(StreamingLog.endpoint % self.run)

    def push(self, lines, start):
        try:
            self.pushing += 1
            res = self.client.post(StreamingLog.endpoint % self.run, 
                json={'start': start, 'lines': lines})
            res.raise_for_status()
            self.pushing -= 1
            self.pushed_at = time.time()
            return res
        except Exception as err:
            if self.pushing > 3:
                raise err
            if os.getenv("DEBUG"):
                sys.stderr.write('Unable to post to WandB: %s' % err)
                traceback.print_exc()
            self.pushing -= 1
            return False