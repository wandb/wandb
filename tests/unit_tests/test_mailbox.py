# from unittest.mock import Mock, MagicMock
#
from wandb.proto import wandb_internal_pb2 as pb
# from wandb.sdk.interface.interface_shared import InterfaceShared
from wandb.sdk.lib.mailbox import Mailbox


def get_test_setup():
    mailbox = Mailbox()
    handle = mailbox.get_handle()
    run_result = pb.RunUpdateResult()
    run_result.run.run_id = "this_is_me"
    result = pb.Result(run_result=run_result)
    return mailbox, handle, result


def test_normal():
    mailbox, handle, result = get_test_setup()
    result.control.mailbox_slot = handle.address
    mailbox.deliver(result)
    got_result = handle.wait(timeout=-1)
    assert got_result.run_result.run.run_id == "this_is_me"


def test_deliver_wrong_slot():
    mailbox, handle, result = get_test_setup()
    result.control.mailbox_slot = "bad_mail_slot"
    mailbox.deliver(result)
    got_result = handle.wait(timeout=1)
    assert got_result is None


def test_deliver_released_slot():
    mailbox, handle, result = get_test_setup()
    result.control.mailbox_slot = handle.address
    mailbox.deliver(result)
    got_result = handle.wait(timeout=-1)
    assert got_result.run_result.run.run_id == "this_is_me"

    # mail slot has been released, lets redeliver to nowhere
    result2 = pb.Result()
    result2.CopyFrom(result)
    result2.run_result.run.run_id = "this_is_new"
    mailbox.deliver(result2)

    # our handler should timeout
    got_result = handle.wait(timeout=1)
    assert got_result is None


def test_redeliver_slot():
    mailbox, handle, result = get_test_setup()
    result.control.mailbox_slot = handle.address
    mailbox.deliver(result)
    got_result = handle.wait(timeout=-1, release=False)
    assert got_result.run_result.run.run_id == "this_is_me"

    # mail slot has been released, lets redeliver to nowhere
    result2 = pb.Result()
    result2.CopyFrom(result)
    result2.run_result.run.run_id = "this_is_new"
    mailbox.deliver(result2)

    # our handler should see the old data
    got_result = handle.wait(timeout=-1)
    assert got_result.run_result.run.run_id == "this_is_new"


def test_on_probe():
    def on_probe(probe_handle):
        pass

    mailbox, handle, result = get_test_setup()
    handle.add_probe(on_probe)
    _ = handle.wait(timeout=3)


def test_on_progress():
    def on_progress(progress_handle):
        pass

    mailbox, handle, result = get_test_setup()
    handle.add_progress(on_progress)
    _ = handle.wait(timeout=3)


# def test_keepalive():
#     mailbox = Mailbox()
#     mailbox.enable_keepalive()
#
#     record = pb.Record()
#     iface = Mock(spec_set=["publish", "_publish", "transport_failed", "_transport_mark_failed", "_transport_mark_success", "_transport_keepalive_failed"])
#     iface.transport_failed = Mock(return_value=False)
#
#     handle = mailbox._deliver_record(record, iface)
#     got_result = handle.wait(timeout=2)
#     assert iface.publish.call_count == 1
#     print("GOT", got_result)
