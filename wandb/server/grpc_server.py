#!/usr/bin/env python
"""WIP wandb grpc server."""

from concurrent import futures
import datetime
import logging
import multiprocessing
import os
import time
import tempfile
import setproctitle

import grpc
import wandb
from wandb.proto import wandb_internal_pb2  # type: ignore
from wandb.proto import wandb_server_pb2  # type: ignore
from wandb.proto import wandb_server_pb2_grpc  # type: ignore


class InternalServiceServicer(wandb_server_pb2_grpc.InternalServiceServicer):
    """Provides methods that implement functionality of route guide server."""

    def __init__(self, server, backend):
        self._server = server
        self._backend = backend

    def RunUpdate(self, run_data, context):  # noqa: N802
        if not run_data.run_id:
            run_data.run_id = wandb.wandb_lib.runid.generate_id()
        # Record telemetry info about grpc server
        run_data.telemetry.feature.grpc = True
        run_data.telemetry.cli_version = wandb.__version__
        result = self._backend._interface._communicate_run(run_data)

        # initiate run (stats and metadata probing)
        # _ = self._backend._interface.communicate_run_start(result.run)

        return result

    def RunStart(self, run_data, context):  # noqa: N802
        # initiate run (stats and metadata probing)
        result = self._backend._interface.communicate_run_start(run_data.run)
        return result

    def PollExit(self, poll_exit, context):  # noqa: N802
        # initiate run (stats and metadata probing)
        result = self._backend._interface.communicate_poll_exit()
        return result

    def GetSummary(self, poll_exit, context):  # noqa: N802
        # initiate run (stats and metadata probing)
        result = self._backend._interface.communicate_summary()
        return result

    def SampledHistory(self, poll_exit, context):  # noqa: N802
        # initiate run (stats and metadata probing)
        result = self._backend._interface.communicate_sampled_history()
        return result

    def Shutdown(self, poll_exit, context):  # noqa: N802
        # initiate run (stats and metadata probing)
        self._backend._interface._communicate_shutdown()
        result = wandb_internal_pb2.ShutdownResponse()
        return result

    def RunExit(self, exit_data, context):  # noqa: N802
        self._backend._interface.publish_exit(exit_data.exit_code)
        result = wandb_internal_pb2.RunExitResult()
        return result

    def Log(self, log_data, context):  # noqa: N802
        # TODO: make this sync?
        self._backend._interface._publish_history(log_data)
        # make up a response even though this was async
        result = wandb_internal_pb2.HistoryResult()
        return result

    def Summary(self, summary_data, context):  # noqa: N802
        # TODO: make this sync?
        self._backend._interface._publish_summary(summary_data)
        # make up a response even though this was async
        result = wandb_internal_pb2.SummaryResult()
        return result

    def Output(self, output_data, context):  # noqa: N802
        # TODO: make this sync?
        self._backend._interface._publish_output(output_data)
        # make up a response even though this was async
        result = wandb_internal_pb2.OutputResult()
        return result

    def Config(self, config_data, context):  # noqa: N802
        # TODO: make this sync?
        self._backend._interface._publish_config(config_data)
        # make up a response even though this was async
        result = wandb_internal_pb2.ConfigResult()
        return result

    def ServerShutdown(self, request, context):  # noqa: N802
        self._backend.cleanup()
        result = wandb_server_pb2.ServerShutdownResult()
        self._server.stop(5)
        return result

    def ServerStatus(self, request, context):  # noqa: N802
        result = wandb_server_pb2.ServerStatusResult()
        return result


# TODO(jhr): this should be merged with code in backend/backend.py ensure launched
class Backend:
    def __init__(self):
        self._done = False
        self._interface = None
        self._record_q = None
        self._result_q = None
        self._settings = None

    def _make_settings(self):
        log_level = logging.DEBUG
        start_time = time.time()
        start_datetime = datetime.datetime.now()
        timespec = datetime.datetime.strftime(start_datetime, "%Y%m%d_%H%M%S")

        wandb_dir = "wandb"
        pid = os.getpid()
        run_path = "run-{}-{}-server".format(timespec, pid)
        run_dir = os.path.join(wandb_dir, run_path)
        files_dir = os.path.join(run_dir, "files")
        sync_file = os.path.join(run_dir, "run-{}.wandb".format(start_time))
        os.makedirs(files_dir)
        settings = dict(
            log_internal=os.path.join(run_dir, "internal.log"),
            files_dir=files_dir,
            _start_time=start_time,
            _start_datetime=start_datetime,
            disable_code=None,
            code_program=None,
            save_code=None,
            sync_file=sync_file,
            _internal_queue_timeout=20,
            _internal_check_process=0,
            _disable_meta=True,
            _disable_stats=False,
            git_remote=None,
            program=None,
            resume=None,
            ignore_globs=(),
            offline=None,
            _log_level=log_level,
            run_id=None,
            entity=None,
            project=None,
            run_group=None,
            run_job_type=None,
            run_tags=None,
            run_name=None,
            run_notes=None,
            _jupyter=None,
            _kaggle=None,
            _offline=None,
            email=None,
            silent=None,
        )
        return settings

    def setup(self, process=None, record_q=None, result_q=None, pid=None):
        settings = self._make_settings()
        mp = multiprocessing
        fd_pipe_child, fd_pipe_parent = mp.Pipe()

        record_q = record_q or mp.Queue()
        # TODO: should this be one item just to make sure it stays fully synchronous?
        result_q = result_q or mp.Queue()

        if process:
            wandb_process = process
        else:
            wandb_process = mp.Process(
                target=wandb.wandb_sdk.internal.internal.wandb_internal,
                kwargs=dict(settings=settings, record_q=record_q, result_q=result_q,),
            )
            wandb_process.name = "wandb_internal"
            wandb_process.start()

        self._settings = settings
        self._record_q = record_q
        self._result_q = result_q
        self.wandb_process = wandb_process

        self._interface = wandb.wandb_sdk.interface.interface.BackendSender(
            record_q=record_q,
            result_q=result_q,
            process=wandb_process,
            process_check=False,
        )

    def run(self, port=None):
        try:
            wandb.wandb_sdk.internal.internal.wandb_internal(
                settings=self._settings,
                record_q=self._record_q,
                result_q=self._result_q,
                port=port,
            )
        except KeyboardInterrupt:
            pass

    def cleanup(self):
        # TODO: make _done atomic
        if self._done:
            return
        self._done = True
        self._interface.join()
        # self.wandb_process.join()
        self._record_q.close()
        self._result_q.close()
        # No printing allowed from here until redirect restore!!!


def serve(backend, port, port_filename=None, address=None):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    try:
        wandb_server_pb2_grpc.add_InternalServiceServicer_to_server(
            InternalServiceServicer(server, backend), server
        )
        port = server.add_insecure_port("localhost:{}".format(port))
        server.start()

        if port_filename:
            dname, bname = os.path.split(port_filename)
            f = tempfile.NamedTemporaryFile(
                prefix=bname, dir=dname, mode="w", delete=False
            )
            tmp_filename = f.name
            try:
                with f:
                    f.write("%d" % port)
                os.rename(tmp_filename, port_filename)
            except Exception:
                os.unlink(tmp_filename)
                raise

        # server.wait_for_termination()
    except KeyboardInterrupt:
        backend.cleanup()
        server.stop(0)
        raise
    except Exception as e:
        backend.cleanup()
        server.stop(0)
        raise
    return port


def main(port=None, port_filename=None, address=None, pid=None, run=None, rundir=None):
    logging.basicConfig()
    record_q = multiprocessing.Queue()
    result_q = multiprocessing.Queue()
    proc = multiprocessing.current_process()
    backend = Backend()
    backend.setup(process=proc, record_q=record_q, result_q=result_q, pid=pid)
    port = serve(backend, port or 0, port_filename=port_filename, address=address)
    if port:
        setproctitle.setproctitle("wandb_internal[grpc:{}]".format(port))
    backend.run(port=port)
    backend.cleanup()


if __name__ == "__main__":
    main()
