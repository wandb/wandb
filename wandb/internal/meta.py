# -*- coding: utf-8 -*-
"""
meta.
"""

from datetime import datetime
import json
import logging
import os
import platform
from shutil import copyfile
import sys

from wandb import util
from wandb.interface import interface
from wandb.internal import git_repo


METADATA_FNAME = "wandb-metadata.json"

logger = logging.getLogger(__name__)


class Meta(object):
    """Used to store metadata during and after a run."""

    def __init__(self, settings=None, process_q=None, notify_q=None):
        self._settings = settings
        self.data = {}
        self.fname = os.path.join(self._settings.files_dir, METADATA_FNAME)
        self._interface = interface.BackendSender(
            process_queue=process_q, notify_queue=notify_q,
        )
        self._git = git_repo.GitRepo(
            remote=self._settings["git_remote"]
            if "git_remote" in self._settings.keys()
            else "origin"
        )

    def _save_code(self):
        if "root" not in self.data or "program" not in self.data:
            logger.warn("unable to save code -- program entry not found")

        program = os.path.join(
            self.data["root"],
            os.path.relpath(os.getcwd(), start=self.data["root"]),
            self.data["program"],
        )
        if os.path.exists(program):
            relative_path = os.path.relpath(program, start=self.data["root"])
            # Ignore paths outside of out_dir when using custom dir
            if "../" in relative_path:
                relative_path = os.path.basename(relative_path)
            util.mkdir_exists_ok(
                os.path.join(
                    self._settings.files_dir, "code", os.path.dirname(relative_path)
                )
            )
            saved_program = os.path.join(
                self._settings.files_dir, "code", relative_path
            )
            if not os.path.exists(saved_program):
                copyfile(program, saved_program)
                self.data["codePath"] = relative_path

    def _setup_sys(self):
        self.data["os"] = platform.platform(aliased=True)
        self.data["python"] = platform.python_version()
        self.data["args"] = sys.argv[1:]
        self.data["state"] = "running"
        self.data["heartbeatAt"] = datetime.utcnow().isoformat()
        self.data["startedAt"] = datetime.utcfromtimestamp(
            self._settings._start_time
        ).isoformat()

    def _setup_git(self):
        if self._git.enabled:
            self.data["git"] = {
                "remote": self._git.remote_url,
                "commit": self._git.last_commit,
            }
            self.data["email"] = self._git.email
            self.data["root"] = self._git.root or self.data["root"]

    def probe(self):
        self._setup_sys()
        if not self._settings.disable_code:
            if self._settings.code_program is not None:
                self.data["program"] = self._settings["code_program"]
            self._setup_git()
        if self._settings.save_code:
            self._save_code()

    def write(self):
        with open(self.fname, "w") as f:
            s = json.dumps(self.data, indent=4)
            f.write(s)
            f.write("\n")
        base_name = os.path.basename(self.fname)
        files = dict(files=[(base_name,)])

        if "codePath" in self.data:
            code_bname = os.path.basename(self.data["codePath"])
            files["files"].append((code_bname,))

        self._interface.send_files(files)
