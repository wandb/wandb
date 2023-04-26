from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.lib.mailbox import Mailbox


def get_test_setup():
    mailbox = Mailbox()
    handle = mailbox.get_handle()
    run_result = pb.RunUpdateResult()
    run_result.run.run_id = "this_is_me"
    result = pb.Result(run_result=run_result)
    return mailbox, handle, result
