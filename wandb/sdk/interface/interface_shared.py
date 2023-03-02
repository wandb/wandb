"""InterfaceShared - Derived from InterfaceBase - shared with InterfaceQueue and InterfaceSock.

See interface.py for how interface classes relate to each other.

"""

import logging
import time
from abc import abstractmethod
from multiprocessing.process import BaseProcess
from typing import Any, Optional, cast

import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb
from wandb.util import json_dumps_safer, json_friendly

from ..lib.mailbox import Mailbox, MailboxHandle
from .interface import InterfaceBase
from .message_future import MessageFuture
from .router import MessageRouter

logger = logging.getLogger("wandb")


class InterfaceShared(InterfaceBase):
    process: Optional[BaseProcess]
    _process_check: bool
    _router: Optional[MessageRouter]
    _mailbox: Optional[Mailbox]
    _transport_success_timestamp: float
    _transport_failed: bool

    def __init__(
        self,
        process: Optional[BaseProcess] = None,
        process_check: bool = True,
        mailbox: Optional[Any] = None,
    ) -> None:
        super().__init__()
        self._transport_success_timestamp = time.monotonic()
        self._transport_failed = False
        self._process = process
        self._router = None
        self._process_check = process_check
        self._mailbox = mailbox
        self._init_router()

    @abstractmethod
    def _init_router(self) -> None:
        raise NotImplementedError

    @property
    def transport_failed(self) -> bool:
        return self._transport_failed

    @property
    def transport_success_timestamp(self) -> float:
        return self._transport_success_timestamp

    def _transport_mark_failed(self) -> None:
        self._transport_failed = True

    def _transport_mark_success(self) -> None:
        self._transport_success_timestamp = time.monotonic()

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

    def _make_stats(self, stats_dict: dict) -> pb.StatsRecord:
        stats = pb.StatsRecord()
        stats.stats_type = pb.StatsRecord.StatsType.SYSTEM
        stats.timestamp.GetCurrentTime()  # todo: fix this, this is wrong :)
        for k, v in stats_dict.items():
            item = stats.item.add()
            item.key = k
            item.value_json = json_dumps_safer(json_friendly(v)[0])
        return stats

    def _make_login(self, api_key: Optional[str] = None) -> pb.LoginRequest:
        login = pb.LoginRequest()
        if api_key:
            login.api_key = api_key
        return login

    def _make_request(  # noqa: C901
        self,
        login: Optional[pb.LoginRequest] = None,
        get_summary: Optional[pb.GetSummaryRequest] = None,
        pause: Optional[pb.PauseRequest] = None,
        resume: Optional[pb.ResumeRequest] = None,
        status: Optional[pb.StatusRequest] = None,
        stop_status: Optional[pb.StopStatusRequest] = None,
        network_status: Optional[pb.NetworkStatusRequest] = None,
        poll_exit: Optional[pb.PollExitRequest] = None,
        partial_history: Optional[pb.PartialHistoryRequest] = None,
        sampled_history: Optional[pb.SampledHistoryRequest] = None,
        run_start: Optional[pb.RunStartRequest] = None,
        check_version: Optional[pb.CheckVersionRequest] = None,
        log_artifact: Optional[pb.LogArtifactRequest] = None,
        defer: Optional[pb.DeferRequest] = None,
        attach: Optional[pb.AttachRequest] = None,
        artifact_send: Optional[pb.ArtifactSendRequest] = None,
        artifact_poll: Optional[pb.ArtifactPollRequest] = None,
        artifact_done: Optional[pb.ArtifactDoneRequest] = None,
        server_info: Optional[pb.ServerInfoRequest] = None,
        keepalive: Optional[pb.KeepaliveRequest] = None,
        run_status: Optional[pb.RunStatusRequest] = None,
        sender_mark: Optional[pb.SenderMarkRequest] = None,
        sender_read: Optional[pb.SenderReadRequest] = None,
        status_report: Optional[pb.StatusReportRequest] = None,
        cancel: Optional[pb.CancelRequest] = None,
        summary_record: Optional[pb.SummaryRecordRequest] = None,
        telemetry_record: Optional[pb.TelemetryRecordRequest] = None,
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
        link_artifact: Optional[pb.LinkArtifactRecord] = None,
        use_artifact: Optional[pb.UseArtifactRecord] = None,
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
        elif link_artifact:
            record.link_artifact.CopyFrom(link_artifact)
        elif use_artifact:
            record.use_artifact.CopyFrom(use_artifact)
        else:
            raise Exception("Invalid record")
        return record

    @abstractmethod
    def _publish(self, record: pb.Record, local: Optional[bool] = None) -> None:
        raise NotImplementedError

    def _communicate(
        self, rec: pb.Record, timeout: Optional[int] = 5, local: Optional[bool] = None
    ) -> Optional[pb.Result]:
        return self._communicate_async(rec, local=local).get(timeout=timeout)

    def _communicate_async(
        self, rec: pb.Record, local: Optional[bool] = None
    ) -> MessageFuture:
        assert self._router
        if self._process_check and self._process and not self._process.is_alive():
            raise Exception("The wandb backend process has shutdown")
        future = self._router.send_and_receive(rec, local=local)
        return future

    def communicate_login(
        self, api_key: Optional[str] = None, timeout: Optional[int] = 15
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

    def publish_login(self, api_key: Optional[str] = None) -> None:
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
        self, run: pb.RunRecord, timeout: Optional[int] = None
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

    def _publish_link_artifact(self, link_artifact: pb.LinkArtifactRecord) -> Any:
        rec = self._make_record(link_artifact=link_artifact)
        self._publish(rec)

    def _publish_use_artifact(self, use_artifact: pb.UseArtifactRecord) -> Any:
        rec = self._make_record(use_artifact=use_artifact)
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

    def _publish_keepalive(self, keepalive: pb.KeepaliveRequest) -> None:
        record = self._make_request(keepalive=keepalive)
        self._publish(record)

    def _communicate_server_info(
        self, server_info: pb.ServerInfoRequest
    ) -> Optional[pb.ServerInfoResponse]:
        rec = self._make_request(server_info=server_info)
        result = self._communicate(rec)
        if result is None:
            return None
        server_info_response = result.response.server_info_response
        assert server_info_response
        return server_info_response

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

    def _get_mailbox(self) -> Mailbox:
        mailbox = self._mailbox
        assert mailbox
        return mailbox

    def _deliver_record(self, record: pb.Record) -> MailboxHandle:
        mailbox = self._get_mailbox()
        handle = mailbox._deliver_record(record, interface=self)
        return handle

    def _deliver_run(self, run: pb.RunRecord) -> MailboxHandle:
        record = self._make_record(run=run)
        return self._deliver_record(record)

    def _deliver_run_start(self, run_start: pb.RunStartRequest) -> MailboxHandle:
        record = self._make_request(run_start=run_start)
        return self._deliver_record(record)

    def _deliver_get_summary(self, get_summary: pb.GetSummaryRequest) -> MailboxHandle:
        record = self._make_request(get_summary=get_summary)
        return self._deliver_record(record)

    def _deliver_exit(self, exit_data: pb.RunExitRecord) -> MailboxHandle:
        record = self._make_record(exit=exit_data)
        return self._deliver_record(record)

    def _deliver_poll_exit(self, poll_exit: pb.PollExitRequest) -> MailboxHandle:
        record = self._make_request(poll_exit=poll_exit)
        return self._deliver_record(record)

    def _deliver_stop_status(self, stop_status: pb.StopStatusRequest) -> MailboxHandle:
        record = self._make_request(stop_status=stop_status)
        return self._deliver_record(record)

    def _deliver_attach(self, attach: pb.AttachRequest) -> MailboxHandle:
        record = self._make_request(attach=attach)
        return self._deliver_record(record)

    def _deliver_check_version(
        self, check_version: pb.CheckVersionRequest
    ) -> MailboxHandle:
        record = self._make_request(check_version=check_version)
        return self._deliver_record(record)

    def _deliver_network_status(
        self, network_status: pb.NetworkStatusRequest
    ) -> MailboxHandle:
        record = self._make_request(network_status=network_status)
        return self._deliver_record(record)

    def _deliver_request_server_info(
        self, server_info: pb.ServerInfoRequest
    ) -> MailboxHandle:
        record = self._make_request(server_info=server_info)
        return self._deliver_record(record)

    def _deliver_request_sampled_history(
        self, sampled_history: pb.SampledHistoryRequest
    ) -> MailboxHandle:
        record = self._make_request(sampled_history=sampled_history)
        return self._deliver_record(record)

    def _deliver_request_run_status(
        self, run_status: pb.RunStatusRequest
    ) -> MailboxHandle:
        record = self._make_request(run_status=run_status)
        return self._deliver_record(record)

    def _transport_keepalive_failed(self, keepalive_interval: int = 5) -> bool:
        if self._transport_failed:
            return True

        now = time.monotonic()
        if now < self._transport_success_timestamp + keepalive_interval:
            return False

        try:
            self.publish_keepalive()
        except Exception:
            self._transport_mark_failed()
        else:
            self._transport_mark_success()
        return self._transport_failed

    def join(self) -> None:
        super().join()

        if self._router:
            self._router.join()
