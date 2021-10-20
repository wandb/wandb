#
# -*- coding: utf-8 -*-
"""Backend Sender - Send to internal process

Manage backend sender.

"""

from abc import abstractmethod
import json
import logging
from multiprocessing.process import BaseProcess
import os
from typing import Any, Iterable, Optional, Tuple, Union
from typing import cast
from typing import TYPE_CHECKING

import six
import wandb
from wandb import data_types
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb
from wandb.util import (
    get_h5_typename,
    json_dumps_safer,
    json_dumps_safer_history,
    json_friendly,
    json_friendly_val,
    maybe_compress_summary,
    WandBJSONEncoderOld,
)

from . import summary_record as sr
from .artifacts import ArtifactManifest
from .message_future import MessageFuture
from .router import MessageRouter
from ..wandb_artifacts import Artifact

if TYPE_CHECKING:
    from ..wandb_run import Run
    from six.moves.queue import Queue


logger = logging.getLogger("wandb")


def file_policy_to_enum(policy: str) -> "pb.FilesItem.PolicyType.V":
    if policy == "now":
        enum = pb.FilesItem.PolicyType.NOW
    elif policy == "end":
        enum = pb.FilesItem.PolicyType.END
    elif policy == "live":
        enum = pb.FilesItem.PolicyType.LIVE
    return enum


def file_enum_to_policy(enum: "pb.FilesItem.PolicyType.V") -> str:
    if enum == pb.FilesItem.PolicyType.NOW:
        policy = "now"
    elif enum == pb.FilesItem.PolicyType.END:
        policy = "end"
    elif enum == pb.FilesItem.PolicyType.LIVE:
        policy = "live"
    return policy


class BackendSenderBase(object):
    _run: Optional["Run"]

    def __init__(self) -> None:
        self._run = None

    def _hack_set_run(self, run: "Run") -> None:
        self._run = run
        current_pid = os.getpid()
        self._run._set_iface_pid(current_pid)

    def publish_header(self) -> None:
        header = pb.HeaderRecord()
        self._publish_header(header)

    @abstractmethod
    def _publish_header(self, header: pb.HeaderRecord) -> None:
        raise NotImplementedError

    def communicate_check_version(
        self, current_version: str = None
    ) -> Optional[pb.CheckVersionResponse]:
        check_version = pb.CheckVersionRequest()
        if current_version:
            check_version.current_version = current_version
        ret = self._communicate_check_version(check_version)
        return ret

    @abstractmethod
    def _communicate_check_version(
        self, current_version: pb.CheckVersionRequest
    ) -> Optional[pb.CheckVersionResponse]:
        raise NotImplementedError

    def communicate_status(self) -> Optional[pb.StatusResponse]:
        status = pb.StatusRequest()
        resp = self._communicate_status(status)
        return resp

    @abstractmethod
    def _communicate_status(
        self, status: pb.StatusRequest
    ) -> Optional[pb.StatusResponse]:
        raise NotImplementedError

    def communicate_stop_status(self) -> Optional[pb.StopStatusResponse]:
        status = pb.StopStatusRequest()
        resp = self._communicate_stop_status(status)
        return resp

    @abstractmethod
    def _communicate_stop_status(
        self, status: pb.StopStatusRequest
    ) -> Optional[pb.StopStatusResponse]:
        raise NotImplementedError

    def communicate_network_status(self) -> Optional[pb.NetworkStatusResponse]:
        status = pb.NetworkStatusRequest()
        resp = self._communicate_network_status(status)
        return resp

    @abstractmethod
    def _communicate_network_status(
        self, status: pb.NetworkStatusRequest
    ) -> Optional[pb.NetworkStatusResponse]:
        raise NotImplementedError

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

    def publish_run(self, run_obj: "Run") -> None:
        run = self._make_run(run_obj)
        self._publish_run(run)

    @abstractmethod
    def _publish_run(self, run: pb.RunRecord) -> None:
        raise NotImplementedError

    def publish_config(
        self,
        data: dict = None,
        key: Union[Tuple[str, ...], str] = None,
        val: Any = None,
    ) -> None:
        cfg = self._make_config(data=data, key=key, val=val)

        self._publish_config(cfg)

    @abstractmethod
    def _publish_config(self, cfg: pb.ConfigRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def _publish_metric(self, metric: pb.MetricRecord) -> None:
        raise NotImplementedError

    def communicate_attach(self, attach_id: str) -> Optional[pb.AttachResponse]:
        attach = pb.AttachRequest(attach_id=attach_id)
        resp = self._communicate_attach(attach)
        return resp

    @abstractmethod
    def _communicate_attach(
        self, attach: pb.AttachRequest
    ) -> Optional[pb.AttachResponse]:
        raise NotImplementedError

    def communicate_run(
        self, run_obj: "Run", timeout: int = None
    ) -> Optional[pb.RunUpdateResult]:
        run = self._make_run(run_obj)
        return self._communicate_run(run, timeout=timeout)

    @abstractmethod
    def _communicate_run(
        self, run: pb.RunRecord, timeout: int = None
    ) -> Optional[pb.RunUpdateResult]:
        raise NotImplementedError

    def communicate_run_start(self, run_pb: pb.RunRecord) -> bool:
        run_start = pb.RunStartRequest()
        run_start.run.CopyFrom(run_pb)
        result = self._communicate_run_start(run_start)
        return result is not None

    @abstractmethod
    def _communicate_run_start(
        self, run_start: pb.RunStartRequest
    ) -> Optional[pb.RunStartResponse]:
        raise NotImplementedError

    def _make_summary_from_dict(self, summary_dict: dict) -> pb.SummaryRecord:
        summary = pb.SummaryRecord()
        for k, v in six.iteritems(summary_dict):
            update = summary.update.add()
            update.key = k
            update.value_json = json.dumps(v)
        return summary

    def _summary_encode(self, value: Any, path_from_root: str) -> dict:
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

    def publish_summary(self, summary_record: sr.SummaryRecord) -> None:
        pb_summary_record = self._make_summary(summary_record)
        self._publish_summary(pb_summary_record)

    @abstractmethod
    def _publish_summary(self, summary: pb.SummaryRecord) -> None:
        raise NotImplementedError

    def communicate_get_summary(self) -> Optional[pb.GetSummaryResponse]:
        get_summary = pb.GetSummaryRequest()
        return self._communicate_get_summary(get_summary)

    @abstractmethod
    def _communicate_get_summary(
        self, get_summary: pb.GetSummaryRequest
    ) -> Optional[pb.GetSummaryResponse]:
        raise NotImplementedError

    def communicate_sampled_history(self) -> Optional[pb.SampledHistoryResponse]:
        sampled_history = pb.SampledHistoryRequest()
        resp = self._communicate_sampled_history(sampled_history)
        return resp

    @abstractmethod
    def _communicate_sampled_history(
        self, sampled_history: pb.SampledHistoryRequest
    ) -> Optional[pb.SampledHistoryResponse]:
        raise NotImplementedError

    def _make_files(self, files_dict: dict) -> pb.FilesRecord:
        files = pb.FilesRecord()
        for path, policy in files_dict["files"]:
            f = files.files.add()
            f.path = path
            f.policy = file_policy_to_enum(policy)
        return files

    def publish_files(self, files_dict: dict) -> None:
        files = self._make_files(files_dict)
        self._publish_files(files)

    @abstractmethod
    def _publish_files(self, files: pb.FilesRecord) -> None:
        raise NotImplementedError

    def _make_artifact(self, artifact: Artifact) -> pb.ArtifactRecord:
        proto_artifact = pb.ArtifactRecord()
        proto_artifact.type = artifact.type
        proto_artifact.name = artifact.name
        proto_artifact.client_id = artifact._client_id
        proto_artifact.sequence_client_id = artifact._sequence_client_id
        proto_artifact.digest = artifact.digest
        if artifact.distributed_id:
            proto_artifact.distributed_id = artifact.distributed_id
        if artifact.description:
            proto_artifact.description = artifact.description
        if artifact.metadata:
            proto_artifact.metadata = json.dumps(json_friendly_val(artifact.metadata))  # type: ignore
        proto_artifact.incremental_beta1 = artifact.incremental
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
            if entry.size:
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

    def communicate_artifact(
        self,
        run: "Run",
        artifact: Artifact,
        aliases: Iterable[str],
        is_user_created: bool = False,
        use_after_commit: bool = False,
        finalize: bool = True,
    ) -> MessageFuture:
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
        resp = self._communicate_artifact(log_artifact)
        return resp

    @abstractmethod
    def _communicate_artifact(
        self, log_artifact: pb.LogArtifactRequest
    ) -> MessageFuture:
        raise NotImplementedError

    @abstractmethod
    def _communicate_artifact_send(
        self, artifact_send: pb.ArtifactSendRequest
    ) -> Optional[pb.ArtifactSendResponse]:
        raise NotImplementedError

    @abstractmethod
    def _communicate_artifact_poll(
        self, art_poll: pb.ArtifactPollRequest
    ) -> Optional[pb.ArtifactPollResponse]:
        raise NotImplementedError

    @abstractmethod
    def _publish_artifact_done(self, artifact_done: pb.ArtifactDoneRequest) -> None:
        raise NotImplementedError

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
        self._publish_artifact(proto_artifact)

    @abstractmethod
    def _publish_artifact(self, proto_artifact: pb.ArtifactRecord) -> None:
        raise NotImplementedError

    def publish_tbdata(
        self, log_dir: str, save: bool, root_logdir: Optional[str]
    ) -> None:
        tbrecord = pb.TBRecord()
        tbrecord.log_dir = log_dir
        tbrecord.save = save
        tbrecord.root_dir = root_logdir or ""
        self._publish_tbdata(tbrecord)

    @abstractmethod
    def _publish_tbdata(self, tbrecord: pb.TBRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def _publish_telemetry(self, telem: tpb.TelemetryRecord) -> None:
        raise NotImplementedError

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

    @abstractmethod
    def _publish_history(self, history: pb.HistoryRecord) -> None:
        raise NotImplementedError

    def publish_preempting(self) -> None:
        preempt_rec = pb.RunPreemptingRecord()
        self._publish_preempting(preempt_rec)

    @abstractmethod
    def _publish_preempting(self, preempt_rec: pb.RunPreemptingRecord) -> None:
        raise NotImplementedError

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

    @abstractmethod
    def _publish_output(self, outdata: pb.OutputRecord) -> None:
        raise NotImplementedError

    def publish_pause(self) -> None:
        pause = pb.PauseRequest()
        self._publish_pause(pause)

    @abstractmethod
    def _publish_pause(self, pause: pb.PauseRequest) -> None:
        raise NotImplementedError

    def publish_resume(self) -> None:
        resume = pb.ResumeRequest()
        self._publish_resume(resume)

    @abstractmethod
    def _publish_resume(self, resume: pb.ResumeRequest) -> None:
        raise NotImplementedError

    def publish_alert(
        self, title: str, text: str, level: str, wait_duration: int
    ) -> None:
        proto_alert = pb.AlertRecord()
        proto_alert.title = title
        proto_alert.text = text
        proto_alert.level = level
        proto_alert.wait_duration = wait_duration
        self._publish_alert(proto_alert)

    @abstractmethod
    def _publish_alert(self, alert: pb.AlertRecord) -> None:
        raise NotImplementedError

    def _make_exit(self, exit_code: Optional[int]) -> pb.RunExitRecord:
        exit = pb.RunExitRecord()
        if exit_code is not None:
            exit.exit_code = exit_code
        return exit

    def publish_exit(self, exit_code: Optional[int]) -> None:
        exit_data = self._make_exit(exit_code)
        self._publish_exit(exit_data)

    @abstractmethod
    def _publish_exit(self, exit_data: pb.RunExitRecord) -> None:
        raise NotImplementedError

    def communicate_poll_exit(self) -> Optional[pb.PollExitResponse]:
        poll_exit = pb.PollExitRequest()
        resp = self._communicate_poll_exit(poll_exit)
        return resp

    @abstractmethod
    def _communicate_poll_exit(
        self, poll_exit: pb.PollExitRequest
    ) -> Optional[pb.PollExitResponse]:
        raise NotImplementedError

    def join(self) -> None:
        self._communicate_shutdown()

    @abstractmethod
    def _communicate_shutdown(self) -> None:
        raise NotImplementedError


class BackendSender(BackendSenderBase):
    record_q: Optional["Queue[pb.Record]"]
    result_q: Optional["Queue[pb.Result]"]
    process: Optional[BaseProcess]
    _router: Optional[MessageRouter]
    _process_check: bool

    def __init__(
        self,
        record_q: "Queue[pb.Record]" = None,
        result_q: "Queue[pb.Result]" = None,
        process: BaseProcess = None,
        process_check: bool = True,
    ) -> None:
        super(BackendSender, self).__init__()
        self.record_q = record_q
        self.result_q = result_q
        self._process = process
        self._router = None
        self._process_check = process_check

        self._init_router()

    def _init_router(self) -> None:
        if self.record_q and self.result_q:
            self._router = MessageRouter(self.record_q, self.result_q)

    def _publish_output(self, outdata: pb.OutputRecord) -> None:
        rec = pb.Record()
        rec.output.CopyFrom(outdata)
        self._publish(rec)

    def _publish_tbdata(self, tbrecord: pb.TBRecord) -> None:
        rec = self._make_record(tbrecord=tbrecord)
        self._publish(rec)

    def _publish_history(self, history: pb.HistoryRecord) -> None:
        rec = self._make_record(history=history)
        self._publish(rec)

    def _publish_preempting(self, preempt_rec: pb.RunPreemptingRecord) -> None:
        rec = self._make_record(preempting=preempt_rec)
        self._publish(rec)

    def _publish_telemetry(self, telem: tpb.TelemetryRecord) -> None:
        rec = self._make_record(telemetry=telem)
        self._publish(rec)

    def _make_stats(self, stats_dict: dict) -> pb.StatsRecord:
        stats = pb.StatsRecord()
        stats.stats_type = pb.StatsRecord.StatsType.SYSTEM
        stats.timestamp.GetCurrentTime()
        for k, v in six.iteritems(stats_dict):
            item = stats.item.add()
            item.key = k
            item.value_json = json_dumps_safer(json_friendly(v)[0])  # type: ignore
        return stats

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
        stop_status: pb.StopStatusRequest = None,
        network_status: pb.NetworkStatusRequest = None,
        poll_exit: pb.PollExitRequest = None,
        sampled_history: pb.SampledHistoryRequest = None,
        run_start: pb.RunStartRequest = None,
        check_version: pb.CheckVersionRequest = None,
        log_artifact: pb.LogArtifactRequest = None,
        defer: pb.DeferRequest = None,
        attach: pb.AttachRequest = None,
        artifact_send: pb.ArtifactSendRequest = None,
        artifact_poll: pb.ArtifactPollRequest = None,
        artifact_done: pb.ArtifactDoneRequest = None,
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
        elif stop_status:
            request.stop_status.CopyFrom(stop_status)
        elif network_status:
            request.network_status.CopyFrom(network_status)
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
        elif attach:
            request.attach.CopyFrom(attach)
        elif artifact_send:
            request.artifact_send.CopyFrom(artifact_send)
        elif artifact_poll:
            request.artifact_poll.CopyFrom(artifact_poll)
        elif artifact_done:
            request.artifact_done.CopyFrom(artifact_done)
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
        preempting: pb.RunPreemptingRecord = None,
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
        elif preempting:
            record.preempting.CopyFrom(preempting)
        else:
            raise Exception("Invalid record")
        return record

    def _publish(self, record: pb.Record, local: bool = None) -> None:
        if self._process_check and self._process and not self._process.is_alive():
            raise Exception("The wandb backend process has shutdown")
        if local:
            record.control.local = local
        if self.record_q:
            self.record_q.put(record)

    def _communicate(
        self, rec: pb.Record, timeout: Optional[int] = 5, local: bool = None
    ) -> Optional[pb.Result]:
        return self._communicate_async(rec, local=local).get(timeout=timeout)

    def _communicate_async(self, rec: pb.Record, local: bool = None) -> MessageFuture:
        assert self._router
        if self._process_check and self._process and not self._process.is_alive():
            raise Exception("The wandb backend process has shutdown")
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

    def _publish_defer(self, state: "pb.DeferRequest.DeferState.V") -> None:
        defer = pb.DeferRequest(state=state)
        rec = self._make_request(defer=defer)
        self._publish(rec, local=True)

    def publish_defer(self, state: int = 0) -> None:
        self._publish_defer(cast("pb.DeferRequest.DeferState.V", state))

    def _publish_header(self, header: pb.HeaderRecord) -> None:
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

    def _publish_pause(self, pause: pb.PauseRequest) -> None:
        rec = self._make_request(pause=pause)
        self._publish(rec)

    def _publish_resume(self, resume: pb.ResumeRequest) -> None:
        rec = self._make_request(resume=resume)
        self._publish(rec)

    def _publish_run(self, run: pb.RunRecord) -> None:
        rec = self._make_record(run=run)
        self._publish(rec)

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

    def _communicate_attach(
        self, attach: pb.AttachRequest
    ) -> Optional[pb.AttachResponse]:
        req = self._make_request(attach=attach)
        resp = self._communicate(req)
        if resp is None:
            return None
        return resp.response.attach_response

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

    def publish_stats(self, stats_dict: dict) -> None:
        stats = self._make_stats(stats_dict)
        rec = self._make_record(stats=stats)
        self._publish(rec)

    def _publish_files(self, files: pb.FilesRecord) -> None:
        rec = self._make_record(files=files)
        self._publish(rec)

    def _communicate_artifact(self, log_artifact: pb.LogArtifactRequest) -> Any:
        rec = self._make_request(log_artifact=log_artifact)
        return self._communicate_async(rec)

    def _communicate_artifact_send(
        self, artifact_send: pb.ArtifactSendRequest
    ) -> Optional[pb.ArtifactSendResponse]:
        rec = self._make_request(artifact_send=artifact_send)
        result = self._communicate(rec)
        if result is None:
            return None
        artifact_send_resp = result.response.artifact_send_response
        return artifact_send_resp

    def _communicate_artifact_poll(
        self, artifact_poll: pb.ArtifactPollRequest
    ) -> Optional[pb.ArtifactPollResponse]:
        rec = self._make_request(artifact_poll=artifact_poll)
        result = self._communicate(rec)
        if result is None:
            return None
        artifact_poll_resp = result.response.artifact_poll_response
        return artifact_poll_resp

    def _publish_artifact_done(self, artifact_done: pb.ArtifactDoneRequest) -> None:
        rec = self._make_request(artifact_done=artifact_done)
        self._publish(rec)

    def _publish_artifact(self, proto_artifact: pb.ArtifactRecord) -> None:
        rec = self._make_record(artifact=proto_artifact)
        self._publish(rec)

    def _publish_alert(self, proto_alert: pb.AlertRecord) -> None:
        rec = self._make_record(alert=proto_alert)
        self._publish(rec)

    def _communicate_status(
        self, status: pb.StatusRequest
    ) -> Optional[pb.StatusResponse]:
        req = self._make_request(status=status)
        resp = self._communicate(req, local=True)
        if resp is None:
            return None
        assert resp.response.status_response
        return resp.response.status_response

    def _communicate_stop_status(
        self, status: pb.StopStatusRequest
    ) -> Optional[pb.StopStatusResponse]:
        req = self._make_request(stop_status=status)
        resp = self._communicate(req, local=True)
        if resp is None:
            return None
        assert resp.response.stop_status_response
        return resp.response.stop_status_response

    def _communicate_network_status(
        self, status: pb.NetworkStatusRequest
    ) -> Optional[pb.NetworkStatusResponse]:
        req = self._make_request(network_status=status)
        resp = self._communicate(req, local=True)
        if resp is None:
            return None
        assert resp.response.network_status_response
        return resp.response.network_status_response

    def _publish_exit(self, exit_data: pb.RunExitRecord) -> None:
        rec = self._make_record(exit=exit_data)
        self._publish(rec)

    def _communicate_poll_exit(
        self, poll_exit: pb.PollExitRequest
    ) -> Optional[pb.PollExitResponse]:
        rec = self._make_request(poll_exit=poll_exit)
        result = self._communicate(rec)
        if result is None:
            return None
        poll_exit_response = result.response.poll_exit_response
        assert poll_exit_response
        return poll_exit_response

    def _communicate_check_version(
        self, check_version: pb.CheckVersionRequest
    ) -> Optional[pb.CheckVersionResponse]:
        rec = self._make_request(check_version=check_version)
        result = self._communicate(rec)
        if result is None:
            # Note: timeouts handled by callers: wandb_init.py
            return None
        return result.response.check_version_response

    def _communicate_run_start(
        self, run_start: pb.RunStartRequest
    ) -> Optional[pb.RunStartResponse]:
        rec = self._make_request(run_start=run_start)
        result = self._communicate(rec)
        if result is None:
            return None
        run_start_response = result.response.run_start_response
        return run_start_response

    def _communicate_get_summary(
        self, get_summary: pb.GetSummaryRequest
    ) -> Optional[pb.GetSummaryResponse]:
        record = self._make_request(get_summary=get_summary)
        result = self._communicate(record, timeout=10)
        if result is None:
            return None
        get_summary_response = result.response.get_summary_response
        assert get_summary_response
        return get_summary_response

    def _communicate_sampled_history(
        self, sampled_history: pb.SampledHistoryRequest
    ) -> Optional[pb.SampledHistoryResponse]:
        record = self._make_request(sampled_history=sampled_history)
        result = self._communicate(record)
        if result is None:
            return None
        sampled_history_response = result.response.sampled_history_response
        assert sampled_history_response
        return sampled_history_response

    def _communicate_shutdown(self) -> None:
        # shutdown
        request = pb.Request(shutdown=pb.ShutdownRequest())
        record = self._make_record(request=request)
        _ = self._communicate(record)

    def join(self) -> None:
        super(BackendSender, self).join()

        if self._router:
            self._router.join()
