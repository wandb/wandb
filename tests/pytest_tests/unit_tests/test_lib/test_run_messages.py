import time

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.lib.mailbox import Mailbox

# TODO(mailbox): create a test fixture for this test pattern


def test_status_deliver(mock_run, parse_records, mocked_interface):
    mailbox = Mailbox()
    handle1 = mailbox.get_handle()

    status = pb.RunStatusResponse(sync_items_total=100, sync_items_pending=10)
    status_time = time.time()
    status.sync_time.FromMicroseconds(int(status_time * 1e6))
    response = pb.Response()
    response.run_status_response.CopyFrom(status)
    result = pb.Result()
    result.response.CopyFrom(response)
    result.control.mailbox_slot = handle1.address

    mailbox.deliver(result)
    mocked_interface.deliver_request_run_status = lambda: handle1
    run = mock_run()
    status_obj = run.status()

    assert status_obj.sync_items_total == 100
    assert status_obj.sync_items_pending == 10


def test_check_version_good(mock_run, parse_records, mocked_interface):
    mailbox = Mailbox()
    handle1 = mailbox.get_handle()

    check_version_resp = pb.CheckVersionResponse(upgrade_message="junk")
    response = pb.Response(check_version_response=check_version_resp)
    result = pb.Result(response=response)
    result.control.mailbox_slot = handle1.address

    mailbox.deliver(result)
    mocked_interface.deliver_check_version = lambda current_version: handle1
    run = mock_run()
    run._on_init()
    assert run._check_version.upgrade_message == "junk"


def test_check_version_timeout(mock_run, parse_records, mocked_interface):
    mailbox = Mailbox()
    handle1 = mailbox.get_handle()

    handle1.wait = lambda timeout: None
    mocked_interface.deliver_check_version = lambda current_version: handle1
    run = mock_run()
    run._on_init()
    assert run._check_version is None
