# -*- coding: utf-8 -*-
"""
sender.
"""

from __future__ import print_function

from datetime import datetime
import json
import logging
import os
import time

from wandb.filesync.dir_watcher import DirWatcher
from wandb.interface import interface
from wandb.lib import config_util, filenames, proto_util
from wandb.lib.git import GitRepo
from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.util import sentry_set_scope


# from wandb.stuff import io_wrap

from . import artifacts
from . import file_stream
from . import internal_api
from .file_pusher import FilePusher


logger = logging.getLogger(__name__)


def _config_dict_from_proto_list(obj_list):
    d = dict()
    for item in obj_list:
        d[item.key] = dict(desc=None, value=json.loads(item.value_json))
    return d


class SendManager(object):
    def __init__(
        self, settings, record_q, result_q, interface,
    ):
        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self._interface = interface

        self._fs = None
        self._pusher = None
        self._dir_watcher = None

        # State updated by login
        self._entity = None
        self._flags = None

        # State updated by wandb.init
        self._run = None
        self._project = None

        # State updated by resuming
        self._offsets = {
            "step": 0,
            "history": 0,
            "events": 0,
            "output": 0,
            "runtime": 0,
        }

        # State added when run_exit needs results
        self._exit_sync_uuid = None

        # State added when run_exit is complete
        self._exit_result = None

        self._api = internal_api.Api(default_settings=settings)
        self._api_settings = dict()

        # TODO(jhr): do something better, why do we need to send full lines?
        self._partial_output = dict()

        self._exit_code = 0

    def send(self, record):
        record_type = record.WhichOneof("record_type")
        assert record_type
        handler_str = "send_" + record_type
        send_handler = getattr(self, handler_str, None)
        logger.debug("send: {}".format(record_type))
        assert send_handler, "unknown send handler: {}".format(handler_str)
        send_handler(record)

    def send_request(self, record):
        request_type = record.request.WhichOneof("request_type")
        assert request_type
        handler_str = "send_request_" + request_type
        send_handler = getattr(self, handler_str, None)
        assert send_handler, "unknown handle: {}".format(handler_str)
        send_handler(record)

    def _flatten(self, dictionary):
        if type(dictionary) == dict:
            for k, v in list(dictionary.items()):
                if type(v) == dict:
                    self._flatten(v)
                    dictionary.pop(k)
                    for k2, v2 in v.items():
                        dictionary[k + "." + k2] = v2

    def send_request_status(self, record):
        assert record.control.req_resp

        result = wandb_internal_pb2.Result(uuid=record.uuid)
        status_resp = result.response.status_response
        if record.request.status.check_stop_req:
            status_resp.run_should_stop = False
            if self._entity and self._project and self._run.run_id:
                try:
                    status_resp.run_should_stop = self._api.check_stop_requested(
                        self._project, self._entity, self._run.run_id
                    )
                except Exception as e:
                    logger.warning("Failed to check stop requested status: %s", e)
        self._result_q.put(result)

    def send_request_login(self, record):
        # TODO: do something with api_key or anonymous?
        # TODO: return an error if we aren't logged in?
        self._api.reauth()
        viewer = self._api.viewer()
        # self._login_flags = json.loads(viewer.get("flags", "{}"))
        # self._login_entity = viewer.get("entity")
        login_entity = viewer.get("entity")
        if record.control.req_resp:
            result = wandb_internal_pb2.Result(uuid=record.uuid)
            result.response.login_response.active_entity = login_entity
            self._result_q.put(result)

    def send_exit(self, data):
        exit = data.exit
        self._exit_code = exit.exit_code

        logger.info("handling exit code: %s", exit.exit_code)

        # Pass the responsibility to respond to handle_request_defer()
        if data.control.req_resp:
            self._exit_sync_uuid = data.uuid

        # We need to give the request queue a chance to empty between states
        # so use handle_request_defer as a state machine.
        logger.info("send defer")
        self._interface.publish_defer()

    def send_request_defer(self, data):
        defer = data.request.defer
        state = defer.state
        logger.info("handle sender defer: {}".format(state))

        done = False
        if state == defer.BEGIN:
            pass
        elif state == defer.FLUSH_TB:
            # NOTE: this is handled in handler.py:handle_request_defer()
            pass
        elif state == defer.FLUSH_DIR:
            if self._dir_watcher:
                self._dir_watcher.finish()
                self._dir_watcher = None
        elif state == defer.FLUSH_FP:
            if self._pusher:
                self._pusher.finish()
        elif state == defer.FLUSH_FS:
            if self._fs:
                # TODO(jhr): now is a good time to output pending output lines
                self._fs.finish(self._exit_code)
                self._fs = None
        elif state == defer.END:
            done = True
        else:
            raise AssertionError("unknown state")

        if not done:
            state += 1
            logger.info("send defer: {}".format(state))
            self._interface.publish_defer(state)
            return

        exit_result = wandb_internal_pb2.RunExitResult()

        # This path is not the prefered method to return exit results
        # as it could take a long time to flush the file pusher buffers
        if self._exit_sync_uuid:
            if self._pusher:
                # NOTE: This will block until finished
                self._pusher.print_status()
                self._pusher.join()
                self._pusher = None
            resp = wandb_internal_pb2.Result(
                exit_result=exit_result, uuid=self._exit_sync_uuid
            )
            self._result_q.put(resp)

        # mark exit done in case we are polling on exit
        self._exit_result = exit_result

    def send_request_poll_exit(self, record):
        if not record.control.req_resp:
            return

        result = wandb_internal_pb2.Result(uuid=record.uuid)

        alive = False
        if self._pusher:
            alive, status = self._pusher.get_status()
            file_counts = self._pusher.file_counts_by_category()
            resp = result.response.poll_exit_response
            resp.pusher_stats.uploaded_bytes = status["uploaded_bytes"]
            resp.pusher_stats.total_bytes = status["total_bytes"]
            resp.pusher_stats.deduped_bytes = status["deduped_bytes"]
            resp.file_counts.wandb_count = file_counts["wandb"]
            resp.file_counts.media_count = file_counts["media"]
            resp.file_counts.artifact_count = file_counts["artifact"]
            resp.file_counts.other_count = file_counts["other"]

        if self._exit_result and not alive:
            # pusher join should not block as it was reported as not alive
            self._pusher.join()
            result.response.poll_exit_response.exit_result.CopyFrom(self._exit_result)
            result.response.poll_exit_response.done = True
        self._result_q.put(result)

    def _maybe_setup_resume(self, run):
        """This maybe queries the backend for a run and fails if the settings are
        incompatible."""
        error = None
        if self._settings.resume:
            # TODO: This causes a race, we need to make the upsert atomically
            # only create or update depending on the resume config
            # we use the runs entity if set, otherwise fallback to users entity
            entity = run.entity or self._entity
            logger.info(
                "checking resume status for %s/%s/%s", entity, run.project, run.run_id
            )
            resume_status = self._api.run_resume_status(
                entity=entity, project_name=run.project, name=run.run_id
            )
            logger.info("resume status %s", resume_status)
            if resume_status is None:
                if self._settings.resume == "must":
                    error = wandb_internal_pb2.ErrorInfo()
                    error.code = wandb_internal_pb2.ErrorInfo.ErrorCode.INVALID
                    error.message = (
                        "resume='must' but run (%s) doesn't exist" % run.run_id
                    )
            else:
                if self._settings.resume == "never":
                    error = wandb_internal_pb2.ErrorInfo()
                    error.code = wandb_internal_pb2.ErrorInfo.ErrorCode.INVALID
                    error.message = "resume='never' but run (%s) exists" % run.run_id
                elif self._settings.resume in ("allow", "auto"):
                    history = {}
                    events = {}
                    try:
                        history = json.loads(
                            json.loads(resume_status["historyTail"])[-1]
                        )
                        events = json.loads(json.loads(resume_status["eventsTail"])[-1])
                    except (IndexError, ValueError) as e:
                        logger.error("unable to load resume tails", exc_info=e)
                    # TODO: Do we need to restore config / summary?
                    # System metrics runtime is usually greater than history
                    events_rt = events.get("_runtime", 0)
                    history_rt = history.get("_runtime", 0)
                    self._offsets["runtime"] = max(events_rt, history_rt)
                    self._offsets["step"] = history.get("_step", -1) + 1
                    self._offsets["history"] = resume_status["historyLineCount"]
                    self._offsets["events"] = resume_status["eventsLineCount"]
                    self._offsets["output"] = resume_status["logLineCount"]
                    logger.info("configured resuming with: %s" % self._offsets)
        return error

    def send_run(self, data):
        run = data.run
        run_tags = run.tags[:]
        error = None
        is_wandb_init = self._run is None

        # build config dict
        config_dict = None
        if run.HasField("config"):
            config_dict = _config_dict_from_proto_list(run.config.update)
            config_path = os.path.join(self._settings.files_dir, filenames.CONFIG_FNAME)
            config_util.save_config_file_from_dict(config_path, config_dict)

        repo = GitRepo(remote=self._settings.git_remote)

        if is_wandb_init:
            # Only check resume status on `wandb.init`
            error = self._maybe_setup_resume(run)

        if error is not None:
            if data.control.req_resp:
                resp = wandb_internal_pb2.Result(uuid=data.uuid)
                resp.run_result.run.CopyFrom(run)
                resp.run_result.error.CopyFrom(error)
                self._result_q.put(resp)
            else:
                logger.error("Got error in async mode: %s", error.message)
            return

        # TODO: we don't check inserted currently, ultimately we should make
        # the upsert know the resume state and fail transactionally
        ups, inserted = self._api.upsert_run(
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
            host=run.host or None,
            program_path=self._settings.program or None,
            repo=repo.remote_url,
            commit=repo.last_commit,
        )

        # We subtract the previous runs runtime when resuming
        start_time = run.start_time.ToSeconds() - self._offsets["runtime"]
        self._run = run
        self._run.starting_step = self._offsets["step"]
        self._run.start_time.FromSeconds(start_time)
        storage_id = ups.get("id")
        if storage_id:
            self._run.storage_id = storage_id
        display_name = ups.get("displayName")
        if display_name:
            self._run.display_name = display_name
        project = ups.get("project")
        if project:
            project_name = project.get("name")
            if project_name:
                self._run.project = project_name
                self._project = project_name
            entity = project.get("entity")
            if entity:
                entity_name = entity.get("name")
                if entity_name:
                    self._run.entity = entity_name
                    self._entity = entity_name
        sweep_id = ups.get("sweepName")
        if sweep_id:
            self._run.sweep_id = sweep_id

        if data.control.req_resp:
            resp = wandb_internal_pb2.Result(uuid=data.uuid)
            resp.run_result.run.CopyFrom(self._run)
            self._result_q.put(resp)

        if self._entity is not None:
            self._api_settings["entity"] = self._entity
        if self._project is not None:
            self._api_settings["project"] = self._project

        # Only spin up our threads on the first run message
        if is_wandb_init:
            self._fs = file_stream.FileStreamApi(
                self._api, run.run_id, start_time, settings=self._api_settings
            )
            # Ensure the streaming polices have the proper offsets
            self._fs.set_file_policy(
                "wandb-summary.json", file_stream.SummaryFilePolicy()
            )
            self._fs.set_file_policy(
                "wandb-history.jsonl",
                file_stream.JsonlFilePolicy(start_chunk_id=self._offsets["history"]),
            )
            self._fs.set_file_policy(
                "wandb-events.jsonl",
                file_stream.JsonlFilePolicy(start_chunk_id=self._offsets["events"]),
            )
            self._fs.set_file_policy(
                "output.log",
                file_stream.CRDedupeFilePolicy(start_chunk_id=self._offsets["output"]),
            )
            self._fs.start()
            self._pusher = FilePusher(self._api)
            self._dir_watcher = DirWatcher(self._settings, self._api, self._pusher)
            sentry_set_scope("internal", run.entity, run.project)
            logger.info(
                "run started: %s with start time %s", self._run.run_id, start_time
            )
        else:
            logger.info("updated run: %s", self._run.run_id)

    def _save_history(self, history_dict):
        if self._fs:
            self._fs.push(filenames.HISTORY_FNAME, json.dumps(history_dict))

    def send_history(self, data):
        history = data.history
        history_dict = proto_util.dict_from_proto_list(history.item)
        self._save_history(history_dict)

    def send_summary(self, data):
        summary_dict = proto_util.dict_from_proto_list(data.summary.update)
        json_summary = json.dumps(summary_dict)
        if self._fs:
            self._fs.push(filenames.SUMMARY_FNAME, json_summary)
        # TODO(jhr): we should only write this at the end of the script
        summary_path = os.path.join(self._settings.files_dir, filenames.SUMMARY_FNAME)
        with open(summary_path, "w") as f:
            f.write(json_summary)
            self._save_file(filenames.SUMMARY_FNAME)

    def send_stats(self, data):
        stats = data.stats
        if stats.stats_type != wandb_internal_pb2.StatsRecord.StatsType.SYSTEM:
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
        row["_runtime"] = int(now - self._run.start_time.ToSeconds())
        self._fs.push(filenames.EVENTS_FNAME, json.dumps(row))
        # TODO(jhr): check fs.push results?

    def send_output(self, data):
        if not self._fs:
            return
        out = data.output
        prepend = ""
        stream = "stdout"
        if out.output_type == wandb_internal_pb2.OutputRecord.OutputType.STDERR:
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
            self._fs.push(filenames.OUTPUT_FNAME, line)
            self._partial_output[stream] = ""

    def send_config(self, data):
        cfg = data.config
        config_dict = _config_dict_from_proto_list(cfg.update)
        self._api.upsert_run(
            name=self._run.run_id, config=config_dict, **self._api_settings
        )
        config_path = os.path.join(self._settings.files_dir, "config.yaml")
        config_util.save_config_file_from_dict(config_path, config_dict)
        # TODO(jhr): check result of upsert_run?

    def _save_file(self, fname, policy="end"):
        logger.info("saving file %s with policy %s", fname, policy)
        self._dir_watcher.update_policy(fname, policy)

    def send_files(self, data):
        files = data.files
        for k in files.files:
            # TODO(jhr): fix paths with directories
            self._save_file(k.path, interface.file_enum_to_policy(k.policy))

    def send_tbrecord(self, data):
        # tbrecord watching threads are handled by handler.py
        pass

    def send_artifact(self, data):
        artifact = data.artifact
        saver = artifacts.ArtifactSaver(
            api=self._api,
            digest=artifact.digest,
            manifest_json=artifacts._manifest_json_from_proto(artifact.manifest),
            file_pusher=self._pusher,
            is_user_created=artifact.user_created,
        )

        saver.save(
            type=artifact.type,
            name=artifact.name,
            metadata=artifact.metadata,
            description=artifact.description,
            aliases=artifact.aliases,
            use_after_commit=artifact.use_after_commit,
        )

    def finish(self):
        logger.info("shutting down sender")
        # if self._tb_watcher:
        #     self._tb_watcher.finish()
        if self._dir_watcher:
            self._dir_watcher.finish()
            self._dir_watcher = None
        if self._pusher:
            self._pusher.finish()
            self._pusher.join()
            self._pusher = None
        if self._fs:
            self._fs.finish(self._exit_code)
            self._fs = None
