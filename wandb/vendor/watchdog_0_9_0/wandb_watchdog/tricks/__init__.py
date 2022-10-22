#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2011 Yesudeep Mangalapilly <yesudeep@gmail.com>
# Copyright 2012 Google, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import os
import signal
import subprocess
import time

from wandb_watchdog.utils import echo, has_attribute
from wandb_watchdog.events import PatternMatchingEventHandler


class Trick(PatternMatchingEventHandler):

    """Your tricks should subclass this class."""

    @classmethod
    def generate_yaml(cls):
        context = dict(module_name=cls.__module__,
                       klass_name=cls.__name__)
        template_yaml = """- %(module_name)s.%(klass_name)s:
  args:
  - argument1
  - argument2
  kwargs:
    patterns:
    - "*.py"
    - "*.js"
    ignore_patterns:
    - "version.py"
    ignore_directories: false
"""
        return template_yaml % context


class LoggerTrick(Trick):

    """A simple trick that does only logs events."""

    def on_any_event(self, event):
        pass

    @echo.echo
    def on_modified(self, event):
        pass

    @echo.echo
    def on_deleted(self, event):
        pass

    @echo.echo
    def on_created(self, event):
        pass

    @echo.echo
    def on_moved(self, event):
        pass


class ShellCommandTrick(Trick):

    """Executes shell commands in response to matched events."""

    def __init__(self, shell_command=None, patterns=None, ignore_patterns=None,
                 ignore_directories=False, wait_for_process=False,
                 drop_during_process=False):
        super(ShellCommandTrick, self).__init__(patterns, ignore_patterns,
                                                ignore_directories)
        self.shell_command = shell_command
        self.wait_for_process = wait_for_process
        self.drop_during_process = drop_during_process
        self.process = None

    def on_any_event(self, event):
        from string import Template

        if self.drop_during_process and self.process and self.process.poll() is None:
            return

        if event.is_directory:
            object_type = 'directory'
        else:
            object_type = 'file'

        context = {
            'watch_src_path': event.src_path,
            'watch_dest_path': '',
            'watch_event_type': event.event_type,
            'watch_object': object_type,
        }

        if self.shell_command is None:
            if has_attribute(event, 'dest_path'):
                context.update({'dest_path': event.dest_path})
                command = 'echo "${watch_event_type} ${watch_object} from ${watch_src_path} to ${watch_dest_path}"'
            else:
                command = 'echo "${watch_event_type} ${watch_object} ${watch_src_path}"'
        else:
            if has_attribute(event, 'dest_path'):
                context.update({'watch_dest_path': event.dest_path})
            command = self.shell_command

        command = Template(command).safe_substitute(**context)
        self.process = subprocess.Popen(command, shell=True)
        if self.wait_for_process:
            self.process.wait()


class AutoRestartTrick(Trick):

    """Starts a long-running subprocess and restarts it on matched events.

    The command parameter is a list of command arguments, such as
    ['bin/myserver', '-c', 'etc/myconfig.ini'].

    Call start() after creating the Trick. Call stop() when stopping
    the process.
    """

    def __init__(self, command, patterns=None, ignore_patterns=None,
                 ignore_directories=False, stop_signal=signal.SIGINT,
                 kill_after=10):
        super(AutoRestartTrick, self).__init__(
            patterns, ignore_patterns, ignore_directories)
        self.command = command
        self.stop_signal = stop_signal
        self.kill_after = kill_after
        self.process = None

    def start(self):
        self.process = subprocess.Popen(self.command, preexec_fn=os.setsid)

    def stop(self):
        if self.process is None:
            return
        try:
            os.killpg(os.getpgid(self.process.pid), self.stop_signal)
        except OSError:
            # Process is already gone
            pass
        else:
            kill_time = time.time() + self.kill_after
            while time.time() < kill_time:
                if self.process.poll() is not None:
                    break
                time.sleep(0.25)
            else:
                try:
                    os.killpg(os.getpgid(self.process.pid), 9)
                except OSError:
                    # Process is already gone
                    pass
        self.process = None

    @echo.echo
    def on_any_event(self, event):
        self.stop()
        self.start()
