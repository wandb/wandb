"""InterfaceShared - Derived from InterfaceBase - shared with InterfaceQueue and InterfaceSock.

See interface.py for how interface classes relate to each other.

"""

import logging
from abc import abstractmethod
from typing import Any, Optional, cast

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb
from wandb.sdk.mailbox import Mailbox, MailboxHandle
from wandb.util import json_dumps_safer, json_friendly

from .interface import InterfaceBase

logger = logging.getLogger("wandb")


class InterfaceShared(InterfaceBase):
    def __init__(self, mailbox: Optional[Mailbox] = None) -> None:
        super().__init__()
        self._mailbox = mailbox

    def _publish_output(self, outdata: pb.OutputRecord) -> None:
        rec = pb.Record()
        rec.output.CopyFrom(outdata)
        self._publish(rec)

    def _publish_cancel(self, cancel: pb.CancelRequest) -> None:
        rec = self._make_request(cancel=cancel)
        self._publish(rec)

    def _publish_output_raw(self, outdata: pb.OutputRawRecord) -> None:
        rec = pb.Record()
        rec.output_raw.CopyFrom(outdata)
        self._publish(rec)

    def _publish_tbdata(self, tbrecord: pb.TBRecord) -> None:
        rec = self._make_record(tbrecord=tbrecord)
        self._publish(rec)

    def _publish_partial_history(
        self, partial_history: pb.PartialHistoryRequest
    ) -> None:
        rec = self._make_request(partial_history=partial_history)
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

    def _publish_job_input(
        self, job_input: pb.JobInputRequest
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(job_input=job_input)
        return self._deliver_record(record)

    def _make_stats(self, stats_dict: dict) -> pb.StatsRecord:
        stats = pb.StatsRecord()
        stats.stats_type = pb.StatsRecord.StatsType.SYSTEM
        stats.timestamp.GetCurrentTime()  # todo: fix this, this is wrong :)
        for k, v in stats_dict.items():
            item = stats.item.add()
            item.key = k
            item.value_json = json_dumps_safer(json_friendly(v)[0])
        return stats

    def _make_request(  # noqa: C901
        self,
        get_summary: Optional[pb.GetSummaryRequest] = None,
        pause: Optional[pb.PauseRequest] = None,
        resume: Optional[pb.ResumeRequest] = None,
        status: Optional[pb.StatusRequest] = None,
        stop_status: Optional[pb.StopStatusRequest] = None,
        internal_messages: Optional[pb.InternalMessagesRequest] = None,
        network_status: Optional[pb.NetworkStatusRequest] = None,
        operation_stats: Optional[pb.OperationStatsRequest] = None,
        poll_exit: Optional[pb.PollExitRequest] = None,
        partial_history: Optional[pb.PartialHistoryRequest] = None,
        sampled_history: Optional[pb.SampledHistoryRequest] = None,
        run_start: Optional[pb.RunStartRequest] = None,
        check_version: Optional[pb.CheckVersionRequest] = None,
        log_artifact: Optional[pb.LogArtifactRequest] = None,
        download_artifact: Optional[pb.DownloadArtifactRequest] = None,
        link_artifact: Optional[pb.LinkArtifactRequest] = None,
        defer: Optional[pb.DeferRequest] = None,
        attach: Optional[pb.AttachRequest] = None,
        server_info: Optional[pb.ServerInfoRequest] = None,
        keepalive: Optional[pb.KeepaliveRequest] = None,
        run_status: Optional[pb.RunStatusRequest] = None,
        sender_mark: Optional[pb.SenderMarkRequest] = None,
        sender_read: Optional[pb.SenderReadRequest] = None,
        sync_finish: Optional[pb.SyncFinishRequest] = None,
        status_report: Optional[pb.StatusReportRequest] = None,
        cancel: Optional[pb.CancelRequest] = None,
        summary_record: Optional[pb.SummaryRecordRequest] = None,
        telemetry_record: Optional[pb.TelemetryRecordRequest] = None,
        get_system_metrics: Optional[pb.GetSystemMetricsRequest] = None,
        get_system_metadata: Optional[pb.GetSystemMetadataRequest] = None,
        python_packages: Optional[pb.PythonPackagesRequest] = None,
        job_input: Optional[pb.JobInputRequest] = None,
        run_finish_without_exit: Optional[pb.RunFinishWithoutExitRequest] = None,
        metadata: Optional[pb.MetadataRequest] = None,
    ) -> pb.Record:
        request = pb.Request()
        if get_summary:
            request.get_summary.CopyFrom(get_summary)
        elif pause:
            request.pause.CopyFrom(pause)
        elif resume:
            request.resume.CopyFrom(resume)
        elif status:
            request.status.CopyFrom(status)
        elif stop_status:
            request.stop_status.CopyFrom(stop_status)
        elif internal_messages:
            request.internal_messages.CopyFrom(internal_messages)
        elif network_status:
            request.network_status.CopyFrom(network_status)
        elif operation_stats:
            request.operations.CopyFrom(operation_stats)
        elif poll_exit:
            request.poll_exit.CopyFrom(poll_exit)
        elif partial_history:
            request.partial_history.CopyFrom(partial_history)
        elif sampled_history:
            request.sampled_history.CopyFrom(sampled_history)
        elif run_start:
            request.run_start.CopyFrom(run_start)
        elif check_version:
            request.check_version.CopyFrom(check_version)
        elif log_artifact:
            request.log_artifact.CopyFrom(log_artifact)
        elif download_artifact:
            request.download_artifact.CopyFrom(download_artifact)
        elif link_artifact:
            request.link_artifact.CopyFrom(link_artifact)
        elif defer:
            request.defer.CopyFrom(defer)
        elif attach:
            request.attach.CopyFrom(attach)
        elif server_info:
            request.server_info.CopyFrom(server_info)
        elif keepalive:
            request.keepalive.CopyFrom(keepalive)
        elif run_status:
            request.run_status.CopyFrom(run_status)
        elif sender_mark:
            request.sender_mark.CopyFrom(sender_mark)
        elif sender_read:
            request.sender_read.CopyFrom(sender_read)
        elif cancel:
            request.cancel.CopyFrom(cancel)
        elif status_report:
            request.status_report.CopyFrom(status_report)
        elif summary_record:
            request.summary_record.CopyFrom(summary_record)
        elif telemetry_record:
            request.telemetry_record.CopyFrom(telemetry_record)
        elif get_system_metrics:
            request.get_system_metrics.CopyFrom(get_system_metrics)
        elif get_system_metadata:
            request.get_system_metadata.CopyFrom(get_system_metadata)
        elif sync_finish:
            request.sync_finish.CopyFrom(sync_finish)
        elif python_packages:
            request.python_packages.CopyFrom(python_packages)
        elif job_input:
            request.job_input.CopyFrom(job_input)
        elif run_finish_without_exit:
            request.run_finish_without_exit.CopyFrom(run_finish_without_exit)
        elif metadata:
            request.metadata.CopyFrom(metadata)
        else:
            raise Exception("Invalid request")
        record = self._make_record(request=request)
        # All requests do not get persisted
        record.control.local = True
        if status_report:
            record.control.flow_control = True
        return record

    def _make_record(  # noqa: C901
        self,
        run: Optional[pb.RunRecord] = None,
        config: Optional[pb.ConfigRecord] = None,
        files: Optional[pb.FilesRecord] = None,
        summary: Optional[pb.SummaryRecord] = None,
        history: Optional[pb.HistoryRecord] = None,
        stats: Optional[pb.StatsRecord] = None,
        exit: Optional[pb.RunExitRecord] = None,
        artifact: Optional[pb.ArtifactRecord] = None,
        tbrecord: Optional[pb.TBRecord] = None,
        alert: Optional[pb.AlertRecord] = None,
        final: Optional[pb.FinalRecord] = None,
        metric: Optional[pb.MetricRecord] = None,
        header: Optional[pb.HeaderRecord] = None,
        footer: Optional[pb.FooterRecord] = None,
        request: Optional[pb.Request] = None,
        telemetry: Optional[tpb.TelemetryRecord] = None,
        preempting: Optional[pb.RunPreemptingRecord] = None,
        use_artifact: Optional[pb.UseArtifactRecord] = None,
        output: Optional[pb.OutputRecord] = None,
        output_raw: Optional[pb.OutputRawRecord] = None,
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
        elif use_artifact:
            record.use_artifact.CopyFrom(use_artifact)
        elif output:
            record.output.CopyFrom(output)
        elif output_raw:
            record.output_raw.CopyFrom(output_raw)
        else:
            raise Exception("Invalid record")
        return record

    @abstractmethod
    def _publish(self, record: pb.Record, local: Optional[bool] = None) -> None:
        raise NotImplementedError

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

    def _publish_summary(self, summary: pb.SummaryRecord) -> None:
        rec = self._make_record(summary=summary)
        self._publish(rec)

    def _publish_metadata(self, metadata: pb.MetadataRequest) -> None:
        rec = self._make_request(metadata=metadata)
        self._publish(rec)

    def _publish_metric(self, metric: pb.MetricRecord) -> None:
        rec = self._make_record(metric=metric)
        self._publish(rec)

    def publish_stats(self, stats_dict: dict) -> None:
        stats = self._make_stats(stats_dict)
        rec = self._make_record(stats=stats)
        self._publish(rec)

    def _publish_python_packages(
        self, python_packages: pb.PythonPackagesRequest
    ) -> None:
        rec = self._make_request(python_packages=python_packages)
        self._publish(rec)

    def _publish_files(self, files: pb.FilesRecord) -> None:
        rec = self._make_record(files=files)
        self._publish(rec)

    def _publish_use_artifact(self, use_artifact: pb.UseArtifactRecord) -> Any:
        rec = self._make_record(use_artifact=use_artifact)
        self._publish(rec)

    def _deliver_artifact(
        self,
        log_artifact: pb.LogArtifactRequest,
    ) -> MailboxHandle[pb.Result]:
        rec = self._make_request(log_artifact=log_artifact)
        return self._deliver_record(rec)

    def _deliver_download_artifact(
        self, download_artifact: pb.DownloadArtifactRequest
    ) -> MailboxHandle[pb.Result]:
        rec = self._make_request(download_artifact=download_artifact)
        return self._deliver_record(rec)

    def _deliver_link_artifact(
        self, link_artifact: pb.LinkArtifactRequest
    ) -> MailboxHandle[pb.Result]:
        rec = self._make_request(link_artifact=link_artifact)
        return self._deliver_record(rec)

    def _publish_artifact(self, proto_artifact: pb.ArtifactRecord) -> None:
        rec = self._make_record(artifact=proto_artifact)
        self._publish(rec)

    def _publish_alert(self, proto_alert: pb.AlertRecord) -> None:
        rec = self._make_record(alert=proto_alert)
        self._publish(rec)

    def _deliver_status(
        self,
        status: pb.StatusRequest,
    ) -> MailboxHandle[pb.Result]:
        req = self._make_request(status=status)
        return self._deliver_record(req)

    def _publish_exit(self, exit_data: pb.RunExitRecord) -> None:
        rec = self._make_record(exit=exit_data)
        self._publish(rec)

    def _publish_keepalive(self, keepalive: pb.KeepaliveRequest) -> None:
        record = self._make_request(keepalive=keepalive)
        self._publish(record)

    def _deliver_shutdown(self) -> MailboxHandle[pb.Result]:
        request = pb.Request(shutdown=pb.ShutdownRequest())
        record = self._make_record(request=request)
        return self._deliver_record(record)

    def _get_mailbox(self) -> Mailbox:
        mailbox = self._mailbox
        assert mailbox
        return mailbox

    def _deliver_record(self, record: pb.Record) -> MailboxHandle[pb.Result]:
        mailbox = self._get_mailbox()

        handle = mailbox.require_response(record)
        self._publish(record)

        return handle.map(lambda resp: resp.result_communicate)

    def _deliver_run(self, run: pb.RunRecord) -> MailboxHandle[pb.Result]:
        record = self._make_record(run=run)
        return self._deliver_record(record)

    def _deliver_finish_sync(
        self,
        sync_finish: pb.SyncFinishRequest,
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(sync_finish=sync_finish)
        return self._deliver_record(record)

    def _deliver_run_start(
        self,
        run_start: pb.RunStartRequest,
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(run_start=run_start)
        return self._deliver_record(record)

    def _deliver_get_summary(
        self,
        get_summary: pb.GetSummaryRequest,
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(get_summary=get_summary)
        return self._deliver_record(record)

    def _deliver_get_system_metrics(
        self, get_system_metrics: pb.GetSystemMetricsRequest
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(get_system_metrics=get_system_metrics)
        return self._deliver_record(record)

    def _deliver_get_system_metadata(
        self, get_system_metadata: pb.GetSystemMetadataRequest
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(get_system_metadata=get_system_metadata)
        return self._deliver_record(record)

    def _deliver_exit(
        self,
        exit_data: pb.RunExitRecord,
    ) -> MailboxHandle[pb.Result]:
        record = self._make_record(exit=exit_data)
        return self._deliver_record(record)

    def deliver_operation_stats(self):
        record = self._make_request(operation_stats=pb.OperationStatsRequest())
        return self._deliver_record(record)

    def _deliver_poll_exit(
        self,
        poll_exit: pb.PollExitRequest,
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(poll_exit=poll_exit)
        return self._deliver_record(record)

    def _deliver_finish_without_exit(
        self, run_finish_without_exit: pb.RunFinishWithoutExitRequest
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(run_finish_without_exit=run_finish_without_exit)
        return self._deliver_record(record)

    def _deliver_stop_status(
        self,
        stop_status: pb.StopStatusRequest,
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(stop_status=stop_status)
        return self._deliver_record(record)

    def _deliver_attach(
        self,
        attach: pb.AttachRequest,
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(attach=attach)
        return self._deliver_record(record)

    def _deliver_network_status(
        self, network_status: pb.NetworkStatusRequest
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(network_status=network_status)
        return self._deliver_record(record)

    def _deliver_internal_messages(
        self, internal_message: pb.InternalMessagesRequest
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(internal_messages=internal_message)
        return self._deliver_record(record)

    def _deliver_request_sampled_history(
        self, sampled_history: pb.SampledHistoryRequest
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(sampled_history=sampled_history)
        return self._deliver_record(record)

    def _deliver_request_run_status(
        self, run_status: pb.RunStatusRequest
    ) -> MailboxHandle[pb.Result]:
        record = self._make_request(run_status=run_status)
        return self._deliver_record(record)
