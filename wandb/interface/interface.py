# -*- coding: utf-8 -*-
"""Backend Sender - Send to internal process

Manage backend sender.

"""

import json
import logging

import six
from six.moves import queue
from wandb import data_types
from wandb.interface import constants
from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.util import (
    get_h5_typename,
    json_dumps_safer,
    json_dumps_safer_history,
    json_friendly,
    maybe_compress_summary,
    WandBJSONEncoderOld,
)

logger = logging.getLogger("wandb")


class BackendSender(object):
    class ExceptionTimeout(Exception):
        pass

    def __init__(
        self,
        process_queue=None,
        notify_queue=None,
        request_queue=None,
        response_queue=None,
        process=None,
    ):
        self.process_queue = process_queue
        self.notify_queue = notify_queue
        self.request_queue = request_queue
        self.response_queue = response_queue
        self._run = None
        self._process = process

    def _hack_set_run(self, run):
        self._run = run

    def send_output(self, name, data):
        # from vendor.protobuf import google3.protobuf.timestamp
        # ts = timestamp.Timestamp()
        # ts.GetCurrentTime()
        # now = datetime.now()
        if name == "stdout":
            otype = wandb_internal_pb2.OutputData.OutputType.STDOUT
        elif name == "stderr":
            otype = wandb_internal_pb2.OutputData.OutputType.STDERR
        else:
            # TODO(jhr): throw error?
            print("unknown type")
        o = wandb_internal_pb2.OutputData(output_type=otype, line=data)
        o.timestamp.GetCurrentTime()
        rec = wandb_internal_pb2.Record()
        rec.output.CopyFrom(o)
        self._queue_process(rec)

    def send_history(self, data):
        rec = wandb_internal_pb2.Record()
        data = data_types.history_dict_to_json(self._run, data)
        history = rec.history
        for k, v in six.iteritems(data):
            item = history.item.add()
            item.key = k
            item.value_json = json_dumps_safer_history(v)
        self._queue_process(rec)

    def _make_run(self, run):
        proto_run = wandb_internal_pb2.RunData()
        run._make_proto_run(proto_run)
        proto_run.start_time.GetCurrentTime()
        if run._config is not None:
            config_dict = run._config._as_dict()
            self._make_config(config_dict, obj=proto_run.config)
        return proto_run

    def _make_artifact(self, artifact):
        proto_artifact = wandb_internal_pb2.ArtifactData()
        proto_artifact.type = artifact.type
        proto_artifact.name = artifact.name
        proto_artifact.digest = artifact.digest
        if proto_artifact.description:
            proto_artifact.description = artifact.description
        if proto_artifact.metadata:
            proto_artifact.metadata = artifact.metadata
        self._make_artifact_manifest(artifact.manifest, obj=proto_artifact.manifest)
        return proto_artifact

    def _make_artifact_manifest(self, artifact_manifest, obj=None):
        proto_manifest = obj or wandb_internal_pb2.ArtifactManifest()
        proto_manifest.version = artifact_manifest.version()
        proto_manifest.storage_policy = artifact_manifest.storage_policy.name()

        for k, v in artifact_manifest.storage_policy.config() or {}:
            cfg = proto_manifest.storage_policy_config.add()
            cfg.key = k
            cfg.value_json = json.dumps(v)

        for entry in sorted(artifact_manifest.entries.values(), key=lambda k: k.path):
            proto_entry = proto_manifest.contents.add()
            proto_entry.path = entry.path
            proto_entry.digest = entry.digest
            proto_entry.size = entry.size
            if entry.ref:
                proto_entry.ref = entry.ref
            if entry.local_path:
                proto_entry.local_path = entry.local_path
            for k, v in entry.extra.items():
                proto_extra = proto_entry.extra.add()
                proto_extra.key = k
                proto_extra.value_json = json.dumps(v)
        return proto_manifest

    def _make_exit(self, exit_code):
        exit = wandb_internal_pb2.ExitData()
        exit.exit_code = exit_code
        return exit

    def _make_config(self, config_dict, obj=None):
        config = obj or wandb_internal_pb2.ConfigData()
        for k, v in six.iteritems(config_dict):
            update = config.update.add()
            update.key = k
            update.value_json = json_dumps_safer(json_friendly(v)[0])

        return config

    def _make_stats(self, stats_dict):
        stats = wandb_internal_pb2.StatsData()
        stats.stats_type = wandb_internal_pb2.StatsData.StatsType.SYSTEM
        stats.timestamp.GetCurrentTime()
        for k, v in six.iteritems(stats_dict):
            item = stats.item.add()
            item.key = k
            item.value_json = json_dumps_safer(json_friendly(v)[0])
        return stats

    def _summary_encode(self, value, path_from_root):
        """Normalize, compress, and encode sub-objects for backend storage.

        value: Object to encode.
        path_from_root: `tuple` of key strings from the top-level summary to the
            current `value`.

        Returns:
            A new tree of dict's with large objects replaced with dictionaries
            with "_type" entries that say which type the original data was.
        """

        # Constructs a new `dict` tree in `json_value` that discards and/or
        # encodes objects that aren't JSON serializable.

        if isinstance(value, dict):
            json_value = {}
            for key, value in six.iteritems(value):
                json_value[key] = self._summary_encode(value, path_from_root + (key,))
            return json_value
        else:
            path = ".".join(path_from_root)
            friendly_value, converted = json_friendly(
                data_types.val_to_json(self._run, path, value)
            )
            json_value, compressed = maybe_compress_summary(
                friendly_value, get_h5_typename(value)
            )
            if compressed:
                # TODO(jhr): impleement me
                pass
                # self.write_h5(path_from_root, friendly_value)

            return json_value

    def _make_summary(self, summary_dict):
        data = self._summary_encode(summary_dict, tuple())
        summary = wandb_internal_pb2.SummaryData()
        for k, v in six.iteritems(data):
            update = summary.update.add()
            update.key = k
            update.value_json = json.dumps(json_friendly(v)[0], cls=WandBJSONEncoderOld)
        return summary

    def _make_files(self, files_dict):
        files = wandb_internal_pb2.FilesData()
        for path in files_dict["files"]:
            f = files.files.add()
            f.path[:] = path
        return files

    def _make_record(
        self,
        run=None,
        config=None,
        files=None,
        summary=None,
        stats=None,
        exit=None,
        artifact=None,
    ):
        rec = wandb_internal_pb2.Record()
        if run:
            rec.run.CopyFrom(run)
        if config:
            rec.config.CopyFrom(config)
        if summary:
            rec.summary.CopyFrom(summary)
        if files:
            rec.files.CopyFrom(files)
        if stats:
            rec.stats.CopyFrom(stats)
        if exit:
            rec.exit.CopyFrom(exit)
        if artifact:
            rec.artifact.CopyFrom(artifact)
        return rec

    def _queue_process(self, rec):
        if self._process and not self._process.is_alive():
            raise Exception("problem")
        self.process_queue.put(rec)
        self.notify_queue.put(constants.NOTIFY_PROCESS)

    def _request_flush(self):
        # TODO: make sure request queue is cleared
        # probably need to send a cancel message and
        # wait for it to come back
        pass

    def _request_response(self, rec, timeout=5):
        # TODO: make sure this is called from main process.
        # can only be one outstanding
        # add a cancel queue
        rec.control.req_resp = True
        self.request_queue.put(rec)
        self.notify_queue.put(constants.NOTIFY_REQUEST)

        try:
            rsp = self.response_queue.get(timeout=timeout)
        except queue.Empty:
            self._request_flush()
            # raise BackendSender.ExceptionTimeout("timeout")
            return None

        # returns response, err
        return rsp

    def send_run(self, run_dict):
        run = self._make_run(run_dict)
        rec = self._make_record(run=run)
        self._queue_process(rec)

    def send_config(self, config_dict):
        cfg = self._make_config(config_dict)
        rec = self._make_record(config=cfg)
        self._queue_process(rec)

    def send_summary(self, summary_dict):
        summary = self._make_summary(summary_dict)
        rec = self._make_record(summary=summary)
        self._queue_process(rec)

    def send_run_sync(self, run_dict, timeout=None):
        run = self._make_run(run_dict)
        req = self._make_record(run=run)

        resp = self._request_response(req, timeout=timeout)
        return resp

    def send_stats(self, stats_dict):
        stats = self._make_stats(stats_dict)
        rec = self._make_record(stats=stats)
        self._queue_process(rec)

    def send_files(self, files_dict):
        files = self._make_files(files_dict)
        rec = self._make_record(files=files)
        self._queue_process(rec)

    def send_artifact(
        self, run, artifact, aliases, is_user_created=False, use_after_commit=False
    ):
        proto_run = self._make_run(run)
        proto_artifact = self._make_artifact(artifact)
        proto_artifact.run_id = proto_run.run_id
        proto_artifact.project = proto_run.project
        proto_artifact.entity = proto_run.entity
        proto_artifact.user_created = is_user_created
        proto_artifact.use_after_commit = use_after_commit
        for alias in aliases:
            proto_artifact.aliases.append(alias)
        rec = self._make_record(artifact=proto_artifact)
        self._queue_process(rec)

    def send_exit(self, exit_code):
        pass

    def send_exit_sync(self, exit_code, timeout=None):
        exit = self._make_exit(exit_code)
        req = self._make_record(exit=exit)

        resp = self._request_response(req, timeout=timeout)
        return resp
