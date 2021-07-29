import time
from wandb.proto import wandb_internal_pb2 as pb


def test_runtime(
    internal_hm, mocked_run, mock_server, backend_interface, parse_ctx,
):
    with backend_interface() as interface:

        proto_run = pb.RunRecord()
        mocked_run._make_proto_run(proto_run)

        run_start = pb.RunStartRequest()
        run_start.run.CopyFrom(proto_run)

        record = interface._make_request(run_start=run_start)
        internal_hm.handle_request_run_start(record)

        time.sleep(3)

    ctx_util = parse_ctx(mock_server.ctx)

    assert ctx_util.summary_wandb["runtime"] >= 3


def test_runtime_pause_resume(
    internal_hm, mocked_run, mock_server, backend_interface, parse_ctx,
):
    with backend_interface() as interface:

        proto_run = pb.RunRecord()
        mocked_run._make_proto_run(proto_run)

        run_start = pb.RunStartRequest()
        run_start.run.CopyFrom(proto_run)

        record = interface._make_request(run_start=run_start)
        internal_hm.handle_request_run_start(record)

        time.sleep(3)
        interface.publish_pause()
        time.sleep(3)
        interface.publish_resume()
        time.sleep(3)

    ctx_util = parse_ctx(mock_server.ctx)
    assert 9 >= ctx_util.summary_wandb["runtime"] >= 6


def test_runtime_pause_pause(
    internal_hm, mocked_run, mock_server, backend_interface, parse_ctx,
):
    with backend_interface() as interface:

        proto_run = pb.RunRecord()
        mocked_run._make_proto_run(proto_run)

        run_start = pb.RunStartRequest()
        run_start.run.CopyFrom(proto_run)

        record = interface._make_request(run_start=run_start)
        internal_hm.handle_request_run_start(record)

        time.sleep(3)
        interface.publish_pause()
        time.sleep(3)
        interface.publish_pause()
        time.sleep(3)

    ctx_util = parse_ctx(mock_server.ctx)
    assert 9 >= ctx_util.summary_wandb["runtime"] >= 3


def test_runtime_resume_resume(
    internal_hm, mocked_run, mock_server, backend_interface, parse_ctx,
):
    with backend_interface() as interface:

        proto_run = pb.RunRecord()
        mocked_run._make_proto_run(proto_run)

        run_start = pb.RunStartRequest()
        run_start.run.CopyFrom(proto_run)

        record = interface._make_request(run_start=run_start)
        internal_hm.handle_request_run_start(record)

        time.sleep(3)
        interface.publish_resume()
        time.sleep(3)
        interface.publish_resume()
        time.sleep(3)

    ctx_util = parse_ctx(mock_server.ctx)
    assert ctx_util.summary_wandb["runtime"] >= 9


def test_runtime_resume_pause(
    internal_hm, mocked_run, mock_server, backend_interface, parse_ctx,
):
    with backend_interface() as interface:

        proto_run = pb.RunRecord()
        mocked_run._make_proto_run(proto_run)

        run_start = pb.RunStartRequest()
        run_start.run.CopyFrom(proto_run)

        record = interface._make_request(run_start=run_start)
        internal_hm.handle_request_run_start(record)

        time.sleep(3)
        interface.publish_resume()
        time.sleep(3)
        interface.publish_pause()
        time.sleep(3)

    ctx_util = parse_ctx(mock_server.ctx)
    assert 9 >= ctx_util.summary_wandb["runtime"] >= 6
