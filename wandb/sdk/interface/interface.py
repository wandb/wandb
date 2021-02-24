#
# -*- coding: utf-8 -*-
"""Backend Sender - Send to internal process

Manage backend sender.

"""

import json
import logging
import threading
import uuid

import six
from six.moves import queue
import wandb
from wandb import data_types
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb
from wandb.util import (
    get_h5_typename,
    json_dumps_safer,
    json_dumps_safer_history,
    json_friendly,
    maybe_compress_summary,
    WandBJSONEncoderOld,
)

from .artifacts import ArtifactManifest
from ..wandb_artifacts import Artifact

if wandb.TYPE_CHECKING:
    import typing as t
    from . import summary_record as sr
    from typing import Any, Dict, Iterable, Optional, Tuple, Union
    from multiprocessing import Process
    from typing import cast
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from ..wandb_run import Run
        from six.moves.queue import Queue
else:

    def cast(_, val):
        return val


logger = logging.getLogger("wandb")


def file_policy_to_enum(policy: str) -> "pb.FilesItem.PolicyTypeValue":
    if policy == "now":
        enum = pb.FilesItem.PolicyType.NOW
    elif policy == "end":
        enum = pb.FilesItem.PolicyType.END
    elif policy == "live":
        enum = pb.FilesItem.PolicyType.LIVE
    return enum


def file_enum_to_policy(enum: "pb.FilesItem.PolicyTypeValue") -> str:
    if enum == pb.FilesItem.PolicyType.NOW:
        policy = "now"
    elif enum == pb.FilesItem.PolicyType.END:
        policy = "end"
    elif enum == pb.FilesItem.PolicyType.LIVE:
        policy = "live"
    return policy


class _Future(object):
    _object: Optional[pb.Result]

    def __init__(self) -> None:
        self._object = None
        self._object_ready = threading.Event()
        self._lock = threading.Lock()

    def get(self, timeout: int = None) -> Optional[pb.Result]:
        is_set = self._object_ready.wait(timeout)
        if is_set and self._object:
            return self._object
        return None

    def _set_object(self, obj: pb.Result) -> None:
        self._object = obj
        self._object_ready.set()


class MessageRouter(object):
    _pending_reqs: Dict[str, _Future]
    _request_queue: "Queue[pb.Record]"
    _response_queue: "Queue[pb.Result]"

    def __init__(
        self, request_queue: "Queue[pb.Record]", response_queue: "Queue[pb.Result]"
    ) -> None:
        self._request_queue = request_queue
        self._response_queue = response_queue

        self._pending_reqs = {}
        self._lock = threading.Lock()

        self._join_event = threading.Event()
        self._thread = threading.Thread(target=self.message_loop)
        self._thread.daemon = True
        self._thread.start()

    def message_loop(self) -> None:
        while not self._join_event.is_set():
            try:
                msg = self._response_queue.get(timeout=1)
            except queue.Empty:
                continue
            self._handle_msg_rcv(msg)

    def send_and_receive(self, rec: pb.Record, local: Optional[bool] = None) -> _Future:
        rec.control.req_resp = True
        if local:
            rec.control.local = local
        rec.uuid = uuid.uuid4().hex
        future = _Future()
        with self._lock:
            self._pending_reqs[rec.uuid] = future

        self._request_queue.put(rec)

        return future

    def join(self) -> None:
        self._join_event.set()
        self._thread.join()

    def _handle_msg_rcv(self, msg: pb.Result) -> None:
        with self._lock:
            future = self._pending_reqs.pop(msg.uuid, None)
        if future is None:
            logger.warning("No listener found for msg with uuid %s (%s)", msg.uuid, msg)
            return
        future._set_object(msg)


class BackendSender(object):
    class ExceptionTimeout(Exception):
        pass

    record_q: Optional["Queue[pb.Record]"]
    result_q: Optional["Queue[pb.Result]"]
    process: Optional[Process]
    _run: Optional["Run"]
    _router: Optional[MessageRouter]

    def __init__(
        self,
        record_q: "Queue[pb.Record]" = None,
        result_q: "Queue[pb.Result]" = None,
        process: Process = None,
    ) -> None:
        self.record_q = record_q
        self.result_q = result_q
        self._process = process
        self._run = None
        self._router = None

        if record_q and result_q:
            self._router = MessageRouter(record_q, result_q)

    def _hack_set_run(self, run: "Run") -> None:
        self._run = run

    def publish_output(self, name: str, data: str) -> None:
        # from vendor.protobuf import google3.protobuf.timestamp
        # ts = timestamp.Timestamp()
        # ts.GetCurrentTime()
        # now = datetime.now()
        if name == "stdout":
            otype = pb.OutputRecord.OutputType.STDOUT
        elif name == "stderr":
            otype = pb.OutputRecord.OutputType.STDERR
        else:
            # TODO(jhr): throw error?
            print("unknown type")
        o = pb.OutputRecord(output_type=otype, line=data)
        o.timestamp.GetCurrentTime()
        self._publish_output(o)

    def _publish_output(self, outdata: pb.OutputRecord) -> None:
        rec = pb.Record()
        rec.output.CopyFrom(outdata)
        self._publish(rec)

    def publish_tbdata(
        self, log_dir: str, save: bool, root_logdir: Optional[str]
    ) -> None:
        tbrecord = pb.TBRecord()
        tbrecord.log_dir = log_dir
        tbrecord.save = save
        tbrecord.root_dir = root_logdir or ""
        rec = self._make_record(tbrecord=tbrecord)
        self._publish(rec)

    def _publish_history(self, history: pb.HistoryRecord) -> None:
        rec = self._make_record(history=history)
        self._publish(rec)

    def publish_history(
        self, data: dict, step: int = None, run: "Run" = None, publish_step: bool = True
    ) -> None:
        run = run or self._run
        data = data_types.history_dict_to_json(run, data, step=step)
        history = pb.HistoryRecord()
        if publish_step:
            assert step is not None
            history.step.num = step
        data.pop("_step", None)
        for k, v in six.iteritems(data):
            item = history.item.add()
            item.key = k
            item.value_json = json_dumps_safer_history(v)  # type: ignore
        self._publish_history(history)

    def publish_telemetry(self, telem: tpb.TelemetryRecord) -> None:
        rec = self._make_record(telemetry=telem)
        self._publish(rec)

    def _make_run(self, run: "Run") -> pb.RunRecord:
        proto_run = pb.RunRecord()
        run._make_proto_run(proto_run)
        if run._settings.host:
            proto_run.host = run._settings.host
        if run._config is not None:
            config_dict = run._config._as_dict()  # type: ignore
            self._make_config(data=config_dict, obj=proto_run.config)
        if run._telemetry_obj:
            proto_run.telemetry.MergeFrom(run._telemetry_obj)
        return proto_run

    def _make_artifact(self, artifact: Artifact) -> pb.ArtifactRecord:
        proto_artifact = pb.ArtifactRecord()
        proto_artifact.type = artifact.type
        proto_artifact.name = artifact.name
        proto_artifact.digest = artifact.digest
        if artifact.distributed_id:
            proto_artifact.distributed_id = artifact.distributed_id
        if artifact.description:
            proto_artifact.description = artifact.description
        if artifact.metadata:
            proto_artifact.metadata = json.dumps(artifact.metadata)
        self._make_artifact_manifest(artifact.manifest, obj=proto_artifact.manifest)
        return proto_artifact

    def _make_artifact_manifest(
        self, artifact_manifest: ArtifactManifest, obj: pb.ArtifactManifest = None
    ) -> pb.ArtifactManifest:
        proto_manifest = obj or pb.ArtifactManifest()
        proto_manifest.version = artifact_manifest.version()  # type: ignore
        proto_manifest.storage_policy = artifact_manifest.storage_policy.name()

        for k, v in artifact_manifest.storage_policy.config().items() or {}.items():
            cfg = proto_manifest.storage_policy_config.add()
            cfg.key = k
            cfg.value_json = json.dumps(v)

        for entry in sorted(artifact_manifest.entries.values(), key=lambda k: k.path):  # type: ignore
            proto_entry = proto_manifest.contents.add()
            proto_entry.path = entry.path
            proto_entry.digest = entry.digest
            proto_entry.size = entry.size
            if entry.birth_artifact_id:
                proto_entry.birth_artifact_id = entry.birth_artifact_id
            if entry.ref:
                proto_entry.ref = entry.ref
            if entry.local_path:
                proto_entry.local_path = entry.local_path
            for k, v in entry.extra.items():
                proto_extra = proto_entry.extra.add()
                proto_extra.key = k
                proto_extra.value_json = json.dumps(v)
        return proto_manifest

    def _make_exit(self, exit_code: int) -> pb.RunExitRecord:
        exit = pb.RunExitRecord()
        exit.exit_code = exit_code
        return exit

    def _make_config(
        self,
        data: dict = None,
        key: Union[Tuple[str, ...], str] = None,
        val: Any = None,
        obj: pb.ConfigRecord = None,
    ) -> pb.ConfigRecord:
        config = obj or pb.ConfigRecord()
        if data:
            for k, v in six.iteritems(data):
                update = config.update.add()
                update.key = k
                update.value_json = json_dumps_safer(json_friendly(v)[0])  # type: ignore
        if key:
            update = config.update.add()
            if isinstance(key, tuple):
                for k in key:
                    update.nested_key.append(k)
            else:
                update.key = key
            update.value_json = json_dumps_safer(json_friendly(val)[0])  # type: ignore
        return config

    def _make_stats(self, stats_dict: dict) -> pb.StatsRecord:
        stats = pb.StatsRecord()
        stats.stats_type = pb.StatsRecord.StatsType.SYSTEM
        stats.timestamp.GetCurrentTime()
        for k, v in six.iteritems(stats_dict):
            item = stats.item.add()
            item.key = k
            item.value_json = json_dumps_safer(json_friendly(v)[0])  # type: ignore
        return stats

    def _summary_encode(self, value: t.Any, path_from_root: str) -> dict:
        """Normalize, compress, and encode sub-objects for backend storage.

        value: Object to encode.
        path_from_root: `str` dot separated string from the top-level summary to the
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
                json_value[key] = self._summary_encode(
                    value, path_from_root + "." + key
                )
            return json_value
        else:
            friendly_value, converted = json_friendly(  # type: ignore
                data_types.val_to_json(
                    self._run, path_from_root, value, namespace="summary"
                )
            )
            json_value, compressed = maybe_compress_summary(  # type: ignore
                friendly_value, get_h5_typename(value)  # type: ignore
            )
            if compressed:
                # TODO(jhr): impleement me
                pass
                # self.write_h5(path_from_root, friendly_value)

            return json_value

    def _make_summary_from_dict(self, summary_dict: dict) -> pb.SummaryRecord:
        summary = pb.SummaryRecord()
        for k, v in six.iteritems(summary_dict):
            update = summary.update.add()
            update.key = k
            update.value_json = json.dumps(v)
        return summary

    def _make_summary(self, summary_record: sr.SummaryRecord) -> pb.SummaryRecord:
        pb_summary_record = pb.SummaryRecord()

        for item in summary_record.update:
            pb_summary_item = pb_summary_record.update.add()
            key_length = len(item.key)

            assert key_length > 0

            if key_length > 1:
                pb_summary_item.nested_key.extend(item.key)
            else:
                pb_summary_item.key = item.key[0]

            path_from_root = ".".join(item.key)
            json_value = self._summary_encode(item.value, path_from_root)
            json_value, _ = json_friendly(json_value)  # type: ignore

            pb_summary_item.value_json = json.dumps(
                json_value, cls=WandBJSONEncoderOld,
            )

        for item in summary_record.remove:
            pb_summary_item = pb_summary_record.remove.add()
            key_length = len(item.key)

            assert key_length > 0

            if key_length > 1:
                pb_summary_item.nested_key.extend(item.key)
            else:
                pb_summary_item.key = item.key[0]

        return pb_summary_record

    def _make_files(self, files_dict: dict) -> pb.FilesRecord:
        files = pb.FilesRecord()
        for path, policy in files_dict["files"]:
            f = files.files.add()
            f.path = path
            f.policy = file_policy_to_enum(policy)
        return files

    def _make_login(self, api_key: str = None) -> pb.LoginRequest:
        login = pb.LoginRequest()
        if api_key:
            login.api_key = api_key
        return login

    def _make_request(
        self,
        login: pb.LoginRequest = None,
        get_summary: pb.GetSummaryRequest = None,
        pause: pb.PauseRequest = None,
        resume: pb.ResumeRequest = None,
        status: pb.StatusRequest = None,
        poll_exit: pb.PollExitRequest = None,
        sampled_history: pb.SampledHistoryRequest = None,
        run_start: pb.RunStartRequest = None,
        check_version: pb.CheckVersionRequest = None,
        log_artifact: pb.LogArtifactRequest = None,
        defer: pb.DeferRequest = None,
    ) -> pb.Record:
        request = pb.Request()
        if login:
            request.login.CopyFrom(login)
        elif get_summary:
            request.get_summary.CopyFrom(get_summary)
        elif pause:
            request.pause.CopyFrom(pause)
        elif resume:
            request.resume.CopyFrom(resume)
        elif status:
            request.status.CopyFrom(status)
        elif poll_exit:
            request.poll_exit.CopyFrom(poll_exit)
        elif sampled_history:
            request.sampled_history.CopyFrom(sampled_history)
        elif run_start:
            request.run_start.CopyFrom(run_start)
        elif check_version:
            request.check_version.CopyFrom(check_version)
        elif log_artifact:
            request.log_artifact.CopyFrom(log_artifact)
        elif defer:
            request.defer.CopyFrom(defer)
        else:
            raise Exception("Invalid request")
        record = self._make_record(request=request)
        # All requests do not get persisted
        record.control.local = True
        return record

    def _make_record(
        self,
        run: pb.RunRecord = None,
        config: pb.ConfigRecord = None,
        files: pb.FilesRecord = None,
        summary: pb.SummaryRecord = None,
        history: pb.HistoryRecord = None,
        stats: pb.StatsRecord = None,
        exit: pb.RunExitRecord = None,
        artifact: pb.ArtifactRecord = None,
        tbrecord: pb.TBRecord = None,
        alert: pb.AlertRecord = None,
        final: pb.FinalRecord = None,
        metric: pb.MetricRecord = None,
        header: pb.HeaderRecord = None,
        footer: pb.FooterRecord = None,
        request: pb.Request = None,
        telemetry: tpb.TelemetryRecord = None,
    ) -> pb.Record:
        record = pb.Record()
        if run:
            record.run.CopyFrom(run)
        elif config:
            record.config.CopyFrom(config)
        elif summary:
            record.summary.CopyFrom(summary)
        elif history:
            record.history.CopyFrom(history)
        elif files:
            record.files.CopyFrom(files)
        elif stats:
            record.stats.CopyFrom(stats)
        elif exit:
            record.exit.CopyFrom(exit)
        elif artifact:
            record.artifact.CopyFrom(artifact)
        elif tbrecord:
            record.tbrecord.CopyFrom(tbrecord)
        elif alert:
            record.alert.CopyFrom(alert)
        elif final:
            record.final.CopyFrom(final)
        elif header:
            record.header.CopyFrom(header)
        elif footer:
            record.footer.CopyFrom(footer)
        elif request:
            record.request.CopyFrom(request)
        elif telemetry:
            record.telemetry.CopyFrom(telemetry)
        elif metric:
            record.metric.CopyFrom(metric)
        else:
            raise Exception("Invalid record")
        return record

    def _publish(self, record: pb.Record, local: bool = None) -> None:
        if self._process and not self._process.is_alive():
            raise Exception("The wandb backend process has shutdown")
        if local:
            record.control.local = local
        if self.record_q:
            self.record_q.put(record)

    def _communicate(
        self, rec: pb.Record, timeout: Optional[int] = 5, local: bool = None
    ) -> Optional[pb.Result]:
        return self._communicate_async(rec, local=local).get(timeout=timeout)

    def _communicate_async(self, rec: pb.Record, local: bool = None) -> _Future:
        assert self._router
        future = self._router.send_and_receive(rec, local=local)
        return future

    def communicate_login(
        self, api_key: str = None, timeout: Optional[int] = 15
    ) -> pb.LoginResponse:
        login = self._make_login(api_key)
        rec = self._make_request(login=login)
        result = self._communicate(rec, timeout=timeout)
        if result is None:
            # TODO: friendlier error message here
            raise wandb.Error(
                "Couldn't communicate with backend after %s seconds" % timeout
            )
        login_response = result.response.login_response
        assert login_response
        return login_response

    def _publish_defer(self, state: "pb.DeferRequest.DeferStateValue") -> None:
        defer = pb.DeferRequest(state=state)
        rec = self._make_request(defer=defer)
        self._publish(rec, local=True)

    def publish_defer(self, state: int = 0) -> None:
        self._publish_defer(cast("pb.DeferRequest.DeferStateValue", state))

    def publish_header(self) -> None:
        header = pb.HeaderRecord()
        rec = self._make_record(header=header)
        self._publish(rec)

    def publish_footer(self) -> None:
        footer = pb.FooterRecord()
        rec = self._make_record(footer=footer)
        self._publish(rec)

    def publish_final(self) -> None:
        final = pb.FinalRecord()
        rec = self._make_record(final=final)
        self._publish(rec)

    def publish_login(self, api_key: str = None) -> None:
        login = self._make_login(api_key)
        rec = self._make_request(login=login)
        self._publish(rec)

    def publish_pause(self) -> None:
        pause = pb.PauseRequest()
        rec = self._make_request(pause=pause)
        self._publish(rec)

    def publish_resume(self) -> None:
        resume = pb.ResumeRequest()
        rec = self._make_request(resume=resume)
        self._publish(rec)

    def _publish_run(self, run: pb.RunRecord) -> None:
        rec = self._make_record(run=run)
        self._publish(rec)

    def publish_run(self, run_obj: "Run") -> None:
        run = self._make_run(run_obj)
        self._publish_run(run)

    def publish_config(
        self,
        data: dict = None,
        key: Union[Tuple[str, ...], str] = None,
        val: Any = None,
    ) -> None:
        cfg = self._make_config(data=data, key=key, val=val)
        self._publish_config(cfg)

    def _publish_config(self, cfg: pb.ConfigRecord) -> None:
        rec = self._make_record(config=cfg)
        self._publish(rec)

    def publish_summary(self, summary_record: sr.SummaryRecord) -> None:
        pb_summary_record = self._make_summary(summary_record)
        self._publish_summary(pb_summary_record)

    def _publish_summary(self, summary: pb.SummaryRecord) -> None:
        rec = self._make_record(summary=summary)
        self._publish(rec)

    def _publish_metric(self, metric: pb.MetricRecord) -> None:
        rec = self._make_record(metric=metric)
        self._publish(rec)

    def _communicate_run(
        self, run: pb.RunRecord, timeout: int = None
    ) -> Optional[pb.RunUpdateResult]:
        """Send synchronous run object waiting for a response.

        Arguments:
            run: RunRecord object
            timeout: number of seconds to wait

        Returns:
            RunRecord object
        """

        req = self._make_record(run=run)
        resp = self._communicate(req, timeout=timeout)
        if resp is None:
            logger.info("couldn't get run from backend")
            # Note: timeouts handled by callers: wandb_init.py
            return None
        assert resp.HasField("run_result")
        return resp.run_result

    def communicate_run(
        self, run_obj: "Run", timeout: int = None
    ) -> Optional[pb.RunUpdateResult]:
        run = self._make_run(run_obj)
        return self._communicate_run(run, timeout=timeout)

    def publish_stats(self, stats_dict: dict) -> None:
        stats = self._make_stats(stats_dict)
        rec = self._make_record(stats=stats)
        self._publish(rec)

    def publish_files(self, files_dict: dict) -> None:
        files = self._make_files(files_dict)
        rec = self._make_record(files=files)
        self._publish(rec)

    def communicate_artifact(
        self,
        run: "Run",
        artifact: Artifact,
        aliases: Iterable[str],
        is_user_created: bool = False,
        use_after_commit: bool = False,
        finalize: bool = True,
    ) -> _Future:
        proto_run = self._make_run(run)
        proto_artifact = self._make_artifact(artifact)
        proto_artifact.run_id = proto_run.run_id
        proto_artifact.project = proto_run.project
        proto_artifact.entity = proto_run.entity
        proto_artifact.user_created = is_user_created
        proto_artifact.use_after_commit = use_after_commit
        proto_artifact.finalize = finalize
        for alias in aliases:
            proto_artifact.aliases.append(alias)

        log_artifact = pb.LogArtifactRequest()
        log_artifact.artifact.CopyFrom(proto_artifact)
        rec = self._make_request(log_artifact=log_artifact)
        return self._communicate_async(rec)

    def publish_artifact(
        self,
        run: "Run",
        artifact: Artifact,
        aliases: Iterable[str],
        is_user_created: bool = False,
        use_after_commit: bool = False,
        finalize: bool = True,
    ) -> None:
        proto_run = self._make_run(run)
        proto_artifact = self._make_artifact(artifact)
        proto_artifact.run_id = proto_run.run_id
        proto_artifact.project = proto_run.project
        proto_artifact.entity = proto_run.entity
        proto_artifact.user_created = is_user_created
        proto_artifact.use_after_commit = use_after_commit
        proto_artifact.finalize = finalize
        for alias in aliases:
            proto_artifact.aliases.append(alias)
        rec = self._make_record(artifact=proto_artifact)
        self._publish(rec)

    def publish_alert(
        self, title: str, text: str, level: str, wait_duration: int
    ) -> None:
        proto_alert = pb.AlertRecord()
        proto_alert.title = title
        proto_alert.text = text
        proto_alert.level = level
        proto_alert.wait_duration = wait_duration
        rec = self._make_record(alert=proto_alert)
        self._publish(rec)

    def communicate_status(
        self, check_stop_req: bool, timeout: int = None
    ) -> Optional[pb.StatusResponse]:
        status = pb.StatusRequest()
        status.check_stop_req = check_stop_req
        req = self._make_request(status=status)

        resp = self._communicate(req, timeout=timeout, local=True)
        if resp is None:
            return None
        assert resp.response.status_response
        return resp.response.status_response

    def publish_exit(self, exit_code: int) -> None:
        exit_data = self._make_exit(exit_code)
        rec = self._make_record(exit=exit_data)
        self._publish(rec)

    def _communicate_exit(
        self, exit_data: pb.RunExitRecord, timeout: int = None
    ) -> pb.RunExitResult:
        req = self._make_record(exit=exit_data)

        result = self._communicate(req, timeout=timeout)
        if result is None:
            # TODO: friendlier error message here
            raise wandb.Error(
                "Couldn't communicate with backend after %s seconds" % timeout
            )
        assert result.exit_result
        return result.exit_result

    def communicate_poll_exit(
        self, timeout: int = None
    ) -> Optional[pb.PollExitResponse]:
        poll_request = pb.PollExitRequest()
        rec = self._make_request(poll_exit=poll_request)
        result = self._communicate(rec, timeout=timeout)
        if result is None:
            return None
        poll_exit_response = result.response.poll_exit_response
        assert poll_exit_response
        return poll_exit_response

    def communicate_check_version(
        self, current_version: str = None
    ) -> Optional[pb.CheckVersionResponse]:
        check_version = pb.CheckVersionRequest()
        if current_version:
            check_version.current_version = current_version
        rec = self._make_request(check_version=check_version)
        result = self._communicate(rec)
        if result is None:
            # Note: timeouts handled by callers: wandb_init.py
            return None
        return result.response.check_version_response

    def communicate_run_start(self, run_pb: pb.RunRecord) -> Optional[pb.Result]:
        run_start = pb.RunStartRequest()
        run_start.run.CopyFrom(run_pb)
        rec = self._make_request(run_start=run_start)
        result = self._communicate(rec)
        return result

    def communicate_exit(self, exit_code: int, timeout: int = None) -> pb.RunExitResult:
        exit_data = self._make_exit(exit_code)
        return self._communicate_exit(exit_data, timeout=timeout)

    def communicate_summary(self) -> Optional[pb.GetSummaryResponse]:
        record = self._make_request(get_summary=pb.GetSummaryRequest())
        result = self._communicate(record, timeout=10)
        if result is None:
            return None
        get_summary_response = result.response.get_summary_response
        assert get_summary_response
        return get_summary_response

    def communicate_sampled_history(self) -> Optional[pb.SampledHistoryResponse]:
        record = self._make_request(sampled_history=pb.SampledHistoryRequest())
        result = self._communicate(record)
        if result is None:
            return None
        sampled_history_response = result.response.sampled_history_response
        assert sampled_history_response
        return sampled_history_response

    def join(self) -> None:
        # shutdown
        request = pb.Request(shutdown=pb.ShutdownRequest())
        record = self._make_record(request=request)
        _ = self._communicate(record)

        if self._router:
            self._router.join()
