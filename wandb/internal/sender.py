# -*- coding: utf-8 -*-
"""
internal.
"""

from __future__ import print_function

from datetime import datetime
import json
import logging
import os
import time

from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.util import sentry_set_scope

# from wandb.stuff import io_wrap

from . import file_stream
from . import internal_api
from .file_pusher import FilePusher


logger = logging.getLogger(__name__)


def _dict_from_proto_list(obj_list):
    d = dict()
    for item in obj_list:
        d[item.key] = json.loads(item.value_json)
    return d


def _config_dict_from_proto_list(obj_list):
    d = dict()
    for item in obj_list:
        d[item.key] = dict(desc=None, value=json.loads(item.value_json))
    return d


class SendManager(object):
    def __init__(self, settings, resp_q):
        self._settings = settings
        self._resp_q = resp_q

        self._fs = None
        self._pusher = None

        # is anyone using run_id?
        self._run_id = None

        self._entity = None
        self._project = None

        self._api = internal_api.Api(default_settings=settings)
        self._api_settings = dict()

        # TODO(jhr): do something better, why do we need to send full lines?
        self._partial_output = dict()

        self._exit_code = 0

    def send(self, i):
        t = i.WhichOneof("data")
        if t is None:
            return
        handler = getattr(self, "handle_" + t, None)
        if handler is None:
            print("unknown handle", t)
            return

        # run the handler
        handler(i)

    def _flatten(self, dictionary):
        if type(dictionary) == dict:
            for k, v in list(dictionary.items()):
                if type(v) == dict:
                    self._flatten(v)
                    dictionary.pop(k)
                    for k2, v2 in v.items():
                        dictionary[k + "." + k2] = v2

    def handle_exit(self, data):
        exit = data.exit
        self._exit_code = exit.exit_code

        # Ensure we've at least noticed every file in the run directory. Sometimes
        # we miss things because asynchronously watching filesystems isn't reliable.
        run_dir = self._settings.files_dir
        logger.info("scan: %s", run_dir)

        for dirpath, _, filenames in os.walk(run_dir):
            for fname in filenames:
                file_path = os.path.join(dirpath, fname)
                save_name = os.path.relpath(file_path, run_dir)
                logger.info("scan save: %s %s", file_path, save_name)
                self._save_file(save_name)

        if data.control.req_resp:
            self._resp_q.put(data)

    def handle_run(self, data):
        run = data.run
        run_tags = run.tags[:]

        # build config dict
        config_dict = None
        if run.HasField("config"):
            config_dict = _config_dict_from_proto_list(run.config.update)

        ups = self._api.upsert_run(
            name=run.run_id,
            entity=run.entity or None,
            project=run.project or None,
            group=run.run_group or None,
            job_type=run.job_type or None,
            display_name=run.display_name or None,
            notes=run.notes or None,
            tags=run_tags or None,
            config=config_dict or None,
            sweep_name=run.sweep_id or None,
        )

        if data.control.req_resp:
            storage_id = ups.get("id")
            if storage_id:
                data.run.storage_id = storage_id
            display_name = ups.get("displayName")
            if display_name:
                data.run.display_name = display_name
            project = ups.get("project")
            if project:
                project_name = project.get("name")
                if project_name:
                    data.run.project = project_name
                    self._project = project_name
                entity = project.get("entity")
                if entity:
                    entity_name = entity.get("name")
                    if entity_name:
                        data.run.entity = entity_name
                        self._entity = entity_name
            self._resp_q.put(data)

        if self._entity is not None:
            self._api_settings["entity"] = self._entity
        if self._project is not None:
            self._api_settings["project"] = self._project
        self._fs = file_stream.FileStreamApi(
            self._api, run.run_id, settings=self._api_settings
        )
        self._fs.start()
        self._pusher = FilePusher(self._api)
        self._run_id = run.run_id
        sentry_set_scope("internal", run.entity, run.project)
        logger.info("run started: %s", self._run_id)

    def handle_history(self, data):
        history = data.history
        history_dict = _dict_from_proto_list(history.item)
        if self._fs:
            # print("about to send", d)
            self._fs.push("wandb-history.jsonl", json.dumps(history_dict))
            # print("got", x)

    def handle_summary(self, data):
        summary = data.summary
        summary_dict = _dict_from_proto_list(summary.update)
        if self._fs:
            self._fs.push("wandb-summary.json", json.dumps(summary_dict))

    def handle_stats(self, data):
        stats = data.stats
        if stats.stats_type != wandb_internal_pb2.StatsData.StatsType.SYSTEM:
            return
        if not self._fs:
            return
        now = stats.timestamp.seconds
        d = dict()
        for item in stats.item:
            d[item.key] = json.loads(item.value_json)
        row = dict(system=d)
        self._flatten(row)
        row["_wandb"] = True
        row["_timestamp"] = now
        row["_runtime"] = int(now - self._settings._start_time)
        self._fs.push("wandb-events.jsonl", json.dumps(row))
        # TODO(jhr): check fs.push results?

    def handle_output(self, data):
        out = data.output
        prepend = ""
        stream = "stdout"
        if out.output_type == wandb_internal_pb2.OutputData.OutputType.STDERR:
            stream = "stderr"
            prepend = "ERROR "
        line = out.line
        if not line.endswith("\n"):
            self._partial_output.setdefault(stream, "")
            self._partial_output[stream] += line
            # TODO(jhr): how do we make sure this gets flushed?
            # we might need this for other stuff like telemetry
        else:
            # TODO(jhr): use time from timestamp proto
            # TODO(jhr): do we need to make sure we write full lines?
            # seems to be some issues with line breaks
            cur_time = time.time()
            timestamp = datetime.utcfromtimestamp(cur_time).isoformat() + " "
            prev_str = self._partial_output.get(stream, "")
            line = u"{}{}{}{}".format(prepend, timestamp, prev_str, line)
            self._fs.push("output.log", line)
            self._partial_output[stream] = ""

    def handle_config(self, data):
        cfg = data.config
        config_dict = _config_dict_from_proto_list(cfg.update)
        self._api.upsert_run(
            name=self._run_id, config=config_dict, **self._api_settings
        )
        # TODO(jhr): check result of upsert_run?

    def _save_file(self, fname):
        directory = self._settings.files_dir
        logger.info("saving file %s at %s", fname, directory)
        path = os.path.abspath(os.path.join(directory, fname))
        logger.info("saving file %s at full %s", fname, path)
        self._pusher.update_file(fname, path)
        self._pusher.file_changed(fname, path)

    def handle_files(self, data):
        files = data.files
        for k in files.files:
            fpath = k.path
            # TODO(jhr): fix paths with directories
            fname = fpath[0]
            self._save_file(fname)

    def finish(self):
        if self._pusher:
            self._pusher.finish()
        if self._fs:
            # TODO(jhr): now is a good time to output pending output lines
            self._fs.finish(self._exit_code)
        if self._pusher:
            self._pusher.update_all_files()
            files = self._pusher.files()
            for f in files:
                logger.info("Finish Sync: %s", f)
            self._pusher.print_status()
