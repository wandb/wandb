"""InterfaceShared - Derived from InterfaceBase - shared with InterfaceQueue and InterfaceSock

See interface.py for how interface classes relate to each other.

"""

from abc import abstractmethod
import logging
from multiprocessing.process import BaseProcess
from typing import Any, Optional
from typing import cast

import wandb
from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb
from wandb.util import (
    json_dumps_safer,
    json_friendly,
)

from .interface import InterfaceBase
from .message_future import MessageFuture
from .router import MessageRouter


logger = logging.getLogger("wandb")


class InterfaceShared(InterfaceBase):
    process: Optional[BaseProcess]
    _process_check: bool
    _router: Optional[MessageRouter]

    def __init__(
        self,
        process: BaseProcess = None,
        process_check: bool = True,
    ) -> None:
        super().__init__()
        self._process = process
        self._router = None
        self._process_check = process_check
        self._init_router()

    @abstractmethod
    def _init_router(self) -> None:
        raise NotImplementedError

    def _publish_output(self, outdata: pb.OutputRecord) -> None:
        rec = pb.Record()
        rec.output.CopyFrom(outdata)
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
        stats.timestamp.GetCurrentTime()
        for k, v in stats_dict.items():
            item = stats.item.add()
            item.key = k
            item.value_json = json_dumps_safer(json_friendly(v)[0])
        return stats

    def _make_login(self, api_key: str = None) -> pb.LoginRequest:
        login = pb.LoginRequest()
        if api_key:
            login.api_key = api_key
        return login

    def _make_request(  # noqa: C901
        self,
        login: pb.LoginRequest = None,
        get_summary: pb.GetSummaryRequest = None,
        pause: pb.PauseRequest = None,
        resume: pb.ResumeRequest = None,
        status: pb.StatusRequest = None,
        stop_status: pb.StopStatusRequest = None,
        network_status: pb.NetworkStatusRequest = None,
        poll_exit: pb.PollExitRequest = None,
        partial_history: pb.PartialHistoryRequest = None,
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
        else:
            raise Exception("Invalid request")
        record = self._make_record(request=request)
        # All requests do not get persisted
        record.control.local = True
        return record

    def _make_record(  # noqa: C901
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
        link_artifact: pb.LinkArtifactRecord = None,
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
        else:
            raise Exception("Invalid record")
        return record

    @abstractmethod
    def _publish(self, record: pb.Record, local: bool = None) -> None:
        raise NotImplementedError

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
            raise wandb.Error(  # type: ignore[no-untyped-call]
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

    def _publish_link_artifact(self, link_artifact: pb.LinkArtifactRecord) -> Any:
        rec = self._make_record(link_artifact=link_artifact)
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
        super().join()

        if self._router:
            self._router.join()
