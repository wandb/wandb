# -*- coding: utf-8 -*-
"""
meta.
"""

import json
import os
import sys
import platform
import time
import getpass
import logging
from datetime import datetime

from wandb.interface import interface


METADATA_FNAME = 'wandb-metadata.json'

logger = logging.getLogger(__name__)


class Meta(object):
    """Used to store metadata during and after a run."""

    def __init__(self, settings=None, process_q=None, notify_q=None):
        self._settings = settings
        self.fname = os.path.join(self._settings.files_dir, METADATA_FNAME)
        self.data = {}
        self._interface = interface.BackendSender(
                process_queue=process_q,
                notify_queue=notify_q,
                )

    def probe(self):
        self.data["os"] = platform.platform(aliased=True)
        self.data["python"] = platform.python_version()
        self.data["args"] = sys.argv[1:]
        self.data["state"] = "running"
        self.data["heartbeatAt"] = datetime.utcnow().isoformat()
        self.data["startedAt"] = datetime.utcfromtimestamp(self._settings.start_time).isoformat()

    def write(self):
        with open(self.fname, 'w') as f:
            s = json.dumps(self.data, indent=4)
            f.write(s)
            f.write('\n')
        base_name = os.path.basename(self.fname)
        files = dict(files=[base_name])
        self._interface.send_files(files)
