from wandb.proto import wandb_internal_pb2 as pb
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
    got_result = handle.wait()
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
    got_result = handle.wait()
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
    got_result = handle.wait(release=False)
    assert got_result.run_result.run.run_id == "this_is_me"

    # mail slot has been released, lets redeliver to nowhere
    result2 = pb.Result()
    result2.CopyFrom(result)
    result2.run_result.run.run_id = "this_is_new"
    mailbox.deliver(result2)

    # our handler should see the old data
    got_result = handle.wait()
    assert got_result.run_result.run.run_id == "this_is_new"
