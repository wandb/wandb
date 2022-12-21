from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal import flow_control, settings_static


def test_flow():
    def write_record(record):
        pass

    def forward_record(record):
        pass

    def recover_records(record):
        pass

    settings = settings_static.SettingsStatic({})

    fc = flow_control.FlowControl(
        settings=settings,
        write_record=write_record,
        forward_record=forward_record,
        recover_records=recover_records,
    )

    record = pb.Record()
    fc.flow(record)
