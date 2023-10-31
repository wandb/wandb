"""Interface base class - Used to send messages to the internal process.

InterfaceBase: The abstract class
InterfaceShared: Common routines for socket and queue based implementations
InterfaceQueue: Use multiprocessing queues to send and receive messages
InterfaceSock: Use socket to send and receive messages
InterfaceRelay: Responses are routed to a relay queue (not matching uuids)

"""

import logging
import os
import sys
import time
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Iterable, NewType, Optional, Tuple, Union

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.artifact_manifest import ArtifactManifest
from wandb.sdk.artifacts.staging import get_staging_dir
from wandb.sdk.lib import json_util as json
from wandb.util import (
    WandBJSONEncoderOld,
    get_h5_typename,
    json_dumps_safer,
    json_dumps_safer_history,
    json_friendly,
    json_friendly_val,
    maybe_compress_summary,
)

from ..data_types.utils import history_dict_to_json, val_to_json
from ..lib.mailbox import MailboxHandle
from . import summary_record as sr
from .message_future import MessageFuture

GlobStr = NewType("GlobStr", str)

if TYPE_CHECKING:
    from ..wandb_run import Run

    if sys.version_info >= (3, 8):
        from typing import Literal, TypedDict
    else:
        from typing_extensions import Literal, TypedDict

    PolicyName = Literal["now", "live", "end"]

    class FilesDict(TypedDict):
        files: Iterable[Tuple[GlobStr, PolicyName]]


logger = logging.getLogger("wandb")


def file_policy_to_enum(policy: "PolicyName") -> "pb.FilesItem.PolicyType.V":
    if policy == "now":
        enum = pb.FilesItem.PolicyType.NOW
    elif policy == "end":
        enum = pb.FilesItem.PolicyType.END
    elif policy == "live":
        enum = pb.FilesItem.PolicyType.LIVE
    return enum


def file_enum_to_policy(enum: "pb.FilesItem.PolicyType.V") -> "PolicyName":
    if enum == pb.FilesItem.PolicyType.NOW:
        policy: PolicyName = "now"
    elif enum == pb.FilesItem.PolicyType.END:
        policy = "end"
    elif enum == pb.FilesItem.PolicyType.LIVE:
        policy = "live"
    return policy


class InterfaceBase:
    _run: Optional["Run"]
    _drop: bool

    def __init__(self) -> None:
        self._run = None
        self._drop = False

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

    def communicate_status(self) -> Optional[pb.StatusResponse]:
        status = pb.StatusRequest()
        resp = self._communicate_status(status)
        return resp

    @abstractmethod
    def _communicate_status(
        self, status: pb.StatusRequest
    ) -> Optional[pb.StatusResponse]:
        raise NotImplementedError

    def _make_config(
        self,
        data: Optional[dict] = None,
        key: Optional[Union[Tuple[str, ...], str]] = None,
        val: Optional[Any] = None,
        obj: Optional[pb.ConfigRecord] = None,
    ) -> pb.ConfigRecord:
        config = obj or pb.ConfigRecord()
        if data:
            for k, v in data.items():
                update = config.update.add()
                update.key = k
                update.value_json = json_dumps_safer(json_friendly(v)[0])
        if key:
            update = config.update.add()
            if isinstance(key, tuple):
                for k in key:
                    update.nested_key.append(k)
            else:
                update.key = key
            update.value_json = json_dumps_safer(json_friendly(val)[0])
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

    def publish_run(self, run: "Run") -> None:
        run_record = self._make_run(run)
        self._publish_run(run_record)

    @abstractmethod
    def _publish_run(self, run: pb.RunRecord) -> None:
        raise NotImplementedError

    def publish_cancel(self, cancel_slot: str) -> None:
        cancel = pb.CancelRequest(cancel_slot=cancel_slot)
        self._publish_cancel(cancel)

    @abstractmethod
    def _publish_cancel(self, cancel: pb.CancelRequest) -> None:
        raise NotImplementedError

    def publish_config(
        self,
        data: Optional[dict] = None,
        key: Optional[Union[Tuple[str, ...], str]] = None,
        val: Optional[Any] = None,
    ) -> None:
        cfg = self._make_config(data=data, key=key, val=val)

        self._publish_config(cfg)

    @abstractmethod
    def _publish_config(self, cfg: pb.ConfigRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def _publish_metric(self, metric: pb.MetricRecord) -> None:
        raise NotImplementedError

    def _make_summary_from_dict(self, summary_dict: dict) -> pb.SummaryRecord:
        summary = pb.SummaryRecord()
        for k, v in summary_dict.items():
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
            for key, value in value.items():  # noqa: B020
                json_value[key] = self._summary_encode(
                    value, path_from_root + "." + key
                )
            return json_value
        else:
            friendly_value, converted = json_friendly(
                val_to_json(self._run, path_from_root, value, namespace="summary")
            )
            json_value, compressed = maybe_compress_summary(
                friendly_value, get_h5_typename(value)
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
                json_value,
                cls=WandBJSONEncoderOld,
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

    def _make_files(self, files_dict: "FilesDict") -> pb.FilesRecord:
        files = pb.FilesRecord()
        for path, policy in files_dict["files"]:
            f = files.files.add()
            f.path = path
            f.policy = file_policy_to_enum(policy)
        return files

    def publish_files(self, files_dict: "FilesDict") -> None:
        files = self._make_files(files_dict)
        self._publish_files(files)

    @abstractmethod
    def _publish_files(self, files: pb.FilesRecord) -> None:
        raise NotImplementedError

    def _make_artifact(self, artifact: "Artifact") -> pb.ArtifactRecord:
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
            proto_artifact.metadata = json.dumps(json_friendly_val(artifact.metadata))
        if artifact._base_id:
            proto_artifact.base_id = artifact._base_id

        ttl_duration_input = artifact._ttl_duration_seconds_to_gql()
        if ttl_duration_input:
            proto_artifact.ttl_duration_seconds = ttl_duration_input
        proto_artifact.incremental_beta1 = artifact.incremental
        self._make_artifact_manifest(artifact.manifest, obj=proto_artifact.manifest)
        return proto_artifact

    def _make_artifact_manifest(
        self,
        artifact_manifest: ArtifactManifest,
        obj: Optional[pb.ArtifactManifest] = None,
    ) -> pb.ArtifactManifest:
        proto_manifest = obj or pb.ArtifactManifest()
        proto_manifest.version = artifact_manifest.version()
        proto_manifest.storage_policy = artifact_manifest.storage_policy.name()

        for k, v in artifact_manifest.storage_policy.config().items() or {}.items():
            cfg = proto_manifest.storage_policy_config.add()
            cfg.key = k
            cfg.value_json = json.dumps(v)

        for entry in sorted(artifact_manifest.entries.values(), key=lambda k: k.path):
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

    def publish_link_artifact(
        self,
        run: "Run",
        artifact: "Artifact",
        portfolio_name: str,
        aliases: Iterable[str],
        entity: Optional[str] = None,
        project: Optional[str] = None,
    ) -> None:
        link_artifact = pb.LinkArtifactRecord()
        if artifact.is_draft():
            link_artifact.client_id = artifact._client_id
        else:
            link_artifact.server_id = artifact.id if artifact.id else ""
        link_artifact.portfolio_name = portfolio_name
        link_artifact.portfolio_entity = entity or run.entity
        link_artifact.portfolio_project = project or run.project
        link_artifact.portfolio_aliases.extend(aliases)

        self._publish_link_artifact(link_artifact)

    @abstractmethod
    def _publish_link_artifact(self, link_artifact: pb.LinkArtifactRecord) -> None:
        raise NotImplementedError

    @staticmethod
    def _make_partial_source_str(
        source: Any, job_info: Dict[str, Any], metadata: Dict[str, Any]
    ) -> str:
        """Construct use_artifact.partial.source_info.sourc as str."""
        source_type = job_info.get("source_type", "").strip()
        if source_type == "artifact":
            info_source = job_info.get("source", {})
            source.artifact.artifact = info_source.get("artifact", "")
            source.artifact.entrypoint.extend(info_source.get("entrypoint", []))
            source.artifact.notebook = info_source.get("notebook", False)
        elif source_type == "repo":
            source.git.git_info.remote = metadata.get("git", {}).get("remote", "")
            source.git.git_info.commit = metadata.get("git", {}).get("commit", "")
            source.git.entrypoint.extend(metadata.get("entrypoint", []))
            source.git.notebook = metadata.get("notebook", False)
        elif source_type == "image":
            source.image.image = metadata.get("docker", "")
        else:
            raise ValueError("Invalid source type")

        source_str: str = source.SerializeToString()
        return source_str

    def _make_proto_use_artifact(
        self,
        use_artifact: pb.UseArtifactRecord,
        job_name: str,
        job_info: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> pb.UseArtifactRecord:
        use_artifact.partial.job_name = job_name
        use_artifact.partial.source_info._version = job_info.get("_version", "")
        use_artifact.partial.source_info.source_type = job_info.get("source_type", "")
        use_artifact.partial.source_info.runtime = job_info.get("runtime", "")

        src_str = self._make_partial_source_str(
            source=use_artifact.partial.source_info.source,
            job_info=job_info,
            metadata=metadata,
        )
        use_artifact.partial.source_info.source.ParseFromString(src_str)

        return use_artifact

    def publish_use_artifact(
        self,
        artifact: "Artifact",
    ) -> None:
        assert artifact.id is not None, "Artifact must have an id"

        use_artifact = pb.UseArtifactRecord(
            id=artifact.id,
            type=artifact.type,
            name=artifact.name,
        )

        # TODO(gst): move to internal process
        if "_partial" in artifact.metadata:
            # Download source info from logged partial job artifact
            job_info = {}
            try:
                path = artifact.get_path("wandb-job.json").download()
                with open(path) as f:
                    job_info = json.load(f)
            except Exception as e:
                logger.warning(
                    f"Failed to download partial job info from artifact {artifact}, : {e}"
                )
            use_artifact = self._make_proto_use_artifact(
                use_artifact=use_artifact,
                job_name=artifact.name,
                job_info=job_info,
                metadata=artifact.metadata,
            )

        self._publish_use_artifact(use_artifact)

    @abstractmethod
    def _publish_use_artifact(self, proto_artifact: pb.UseArtifactRecord) -> None:
        raise NotImplementedError

    def communicate_artifact(
        self,
        run: "Run",
        artifact: "Artifact",
        aliases: Iterable[str],
        history_step: Optional[int] = None,
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
        if history_step is not None:
            log_artifact.history_step = history_step
        log_artifact.staging_dir = get_staging_dir()
        resp = self._communicate_artifact(log_artifact)
        return resp

    @abstractmethod
    def _communicate_artifact(
        self, log_artifact: pb.LogArtifactRequest
    ) -> MessageFuture:
        raise NotImplementedError

    def deliver_download_artifact(
        self,
        qualified_name: str,
        download_root: str,
        recursive: bool,
        allow_missing_references: bool,
    ) -> MailboxHandle:
        download_artifact = pb.DownloadArtifactRequest()
        download_artifact.qualified_name = qualified_name
        download_artifact.download_root = download_root
        download_artifact.recursive = recursive
        download_artifact.allow_missing_references = allow_missing_references
        resp = self._deliver_download_artifact(download_artifact)
        return resp

    @abstractmethod
    def _deliver_download_artifact(
        self, download_artifact: pb.DownloadArtifactRequest
    ) -> MailboxHandle:
        raise NotImplementedError

    def publish_artifact(
        self,
        run: "Run",
        artifact: "Artifact",
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

    def publish_tbdata(self, log_dir: str, save: bool, root_logdir: str = "") -> None:
        tbrecord = pb.TBRecord()
        tbrecord.log_dir = log_dir
        tbrecord.save = save
        tbrecord.root_dir = root_logdir
        self._publish_tbdata(tbrecord)

    @abstractmethod
    def _publish_tbdata(self, tbrecord: pb.TBRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def _publish_telemetry(self, telem: tpb.TelemetryRecord) -> None:
        raise NotImplementedError

    def publish_partial_history(
        self,
        data: dict,
        user_step: int,
        step: Optional[int] = None,
        flush: Optional[bool] = None,
        publish_step: bool = True,
        run: Optional["Run"] = None,
    ) -> None:
        run = run or self._run

        data = history_dict_to_json(run, data, step=user_step, ignore_copy_err=True)
        data.pop("_step", None)

        # add timestamp to the history request, if not already present
        # the timestamp might come from the tensorboard log logic
        if "_timestamp" not in data:
            data["_timestamp"] = time.time()

        partial_history = pb.PartialHistoryRequest()
        for k, v in data.items():
            item = partial_history.item.add()
            item.key = k
            item.value_json = json_dumps_safer_history(v)

        if publish_step and step is not None:
            partial_history.step.num = step
        if flush is not None:
            partial_history.action.flush = flush
        self._publish_partial_history(partial_history)

    @abstractmethod
    def _publish_partial_history(self, history: pb.PartialHistoryRequest) -> None:
        raise NotImplementedError

    def publish_history(
        self,
        data: dict,
        step: Optional[int] = None,
        run: Optional["Run"] = None,
        publish_step: bool = True,
    ) -> None:
        run = run or self._run
        data = history_dict_to_json(run, data, step=step)
        history = pb.HistoryRecord()
        if publish_step:
            assert step is not None
            history.step.num = step
        data.pop("_step", None)
        for k, v in data.items():
            item = history.item.add()
            item.key = k
            item.value_json = json_dumps_safer_history(v)
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

    def publish_output_raw(self, name: str, data: str) -> None:
        # from vendor.protobuf import google3.protobuf.timestamp
        # ts = timestamp.Timestamp()
        # ts.GetCurrentTime()
        # now = datetime.now()
        if name == "stdout":
            otype = pb.OutputRawRecord.OutputType.STDOUT
        elif name == "stderr":
            otype = pb.OutputRawRecord.OutputType.STDERR
        else:
            # TODO(jhr): throw error?
            print("unknown type")
        o = pb.OutputRawRecord(output_type=otype, line=data)
        o.timestamp.GetCurrentTime()
        self._publish_output_raw(o)

    @abstractmethod
    def _publish_output_raw(self, outdata: pb.OutputRawRecord) -> None:
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

    def publish_keepalive(self) -> None:
        keepalive = pb.KeepaliveRequest()
        self._publish_keepalive(keepalive)

    @abstractmethod
    def _publish_keepalive(self, keepalive: pb.KeepaliveRequest) -> None:
        raise NotImplementedError

    def join(self) -> None:
        # Drop indicates that the internal process has already been shutdown
        if self._drop:
            return
        _ = self._communicate_shutdown()

    @abstractmethod
    def _communicate_shutdown(self) -> None:
        raise NotImplementedError

    def deliver_run(self, run: "Run") -> MailboxHandle:
        run_record = self._make_run(run)
        return self._deliver_run(run_record)

    @abstractmethod
    def _deliver_run(self, run: pb.RunRecord) -> MailboxHandle:
        raise NotImplementedError

    def deliver_run_start(self, run_pb: pb.RunRecord) -> MailboxHandle:
        run_start = pb.RunStartRequest()
        run_start.run.CopyFrom(run_pb)
        return self._deliver_run_start(run_start)

    @abstractmethod
    def _deliver_run_start(self, run_start: pb.RunStartRequest) -> MailboxHandle:
        raise NotImplementedError

    def deliver_attach(self, attach_id: str) -> MailboxHandle:
        attach = pb.AttachRequest(attach_id=attach_id)
        return self._deliver_attach(attach)

    @abstractmethod
    def _deliver_attach(self, status: pb.AttachRequest) -> MailboxHandle:
        raise NotImplementedError

    def deliver_check_version(
        self, current_version: Optional[str] = None
    ) -> MailboxHandle:
        check_version = pb.CheckVersionRequest()
        if current_version:
            check_version.current_version = current_version
        return self._deliver_check_version(check_version)

    @abstractmethod
    def _deliver_check_version(
        self, check_version: pb.CheckVersionRequest
    ) -> MailboxHandle:
        raise NotImplementedError

    def deliver_stop_status(self) -> MailboxHandle:
        status = pb.StopStatusRequest()
        return self._deliver_stop_status(status)

    @abstractmethod
    def _deliver_stop_status(self, status: pb.StopStatusRequest) -> MailboxHandle:
        raise NotImplementedError

    def deliver_network_status(self) -> MailboxHandle:
        status = pb.NetworkStatusRequest()
        return self._deliver_network_status(status)

    @abstractmethod
    def _deliver_network_status(self, status: pb.NetworkStatusRequest) -> MailboxHandle:
        raise NotImplementedError

    def deliver_internal_messages(self) -> MailboxHandle:
        internal_message = pb.InternalMessagesRequest()
        return self._deliver_internal_messages(internal_message)

    @abstractmethod
    def _deliver_internal_messages(
        self, internal_message: pb.InternalMessagesRequest
    ) -> MailboxHandle:
        raise NotImplementedError

    def deliver_get_summary(self) -> MailboxHandle:
        get_summary = pb.GetSummaryRequest()
        return self._deliver_get_summary(get_summary)

    @abstractmethod
    def _deliver_get_summary(self, get_summary: pb.GetSummaryRequest) -> MailboxHandle:
        raise NotImplementedError

    def deliver_get_system_metrics(self) -> MailboxHandle:
        get_summary = pb.GetSystemMetricsRequest()
        return self._deliver_get_system_metrics(get_summary)

    @abstractmethod
    def _deliver_get_system_metrics(
        self, get_summary: pb.GetSystemMetricsRequest
    ) -> MailboxHandle:
        raise NotImplementedError

    def deliver_exit(self, exit_code: Optional[int]) -> MailboxHandle:
        exit_data = self._make_exit(exit_code)
        return self._deliver_exit(exit_data)

    @abstractmethod
    def _deliver_exit(self, exit_data: pb.RunExitRecord) -> MailboxHandle:
        raise NotImplementedError

    def deliver_poll_exit(self) -> MailboxHandle:
        poll_exit = pb.PollExitRequest()
        return self._deliver_poll_exit(poll_exit)

    @abstractmethod
    def _deliver_poll_exit(self, poll_exit: pb.PollExitRequest) -> MailboxHandle:
        raise NotImplementedError

    def deliver_request_server_info(self) -> MailboxHandle:
        server_info = pb.ServerInfoRequest()
        return self._deliver_request_server_info(server_info)

    @abstractmethod
    def _deliver_request_server_info(
        self, server_info: pb.ServerInfoRequest
    ) -> MailboxHandle:
        raise NotImplementedError

    def deliver_request_sampled_history(self) -> MailboxHandle:
        sampled_history = pb.SampledHistoryRequest()
        return self._deliver_request_sampled_history(sampled_history)

    @abstractmethod
    def _deliver_request_sampled_history(
        self, sampled_history: pb.SampledHistoryRequest
    ) -> MailboxHandle:
        raise NotImplementedError

    def deliver_request_run_status(self) -> MailboxHandle:
        run_status = pb.RunStatusRequest()
        return self._deliver_request_run_status(run_status)

    @abstractmethod
    def _deliver_request_run_status(
        self, run_status: pb.RunStatusRequest
    ) -> MailboxHandle:
        raise NotImplementedError

    def deliver_request_job_info(self) -> MailboxHandle:
        job_info = pb.JobInfoRequest()
        return self._deliver_request_job_info(job_info)

    @abstractmethod
    def _deliver_request_job_info(self, job_info: pb.JobInfoRequest) -> MailboxHandle:
        raise NotImplementedError
