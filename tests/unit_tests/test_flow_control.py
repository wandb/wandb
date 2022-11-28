from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.internal import flow_control, settings_static


def test_flow():
    def write_record(record):
        pass

    def forward_record(record):
        pass

    def ensure_flushed(record):
        pass

    settings = settings_static.SettingsStatic({})

    fc = flow_control.FlowControl(
        settings=settings,
        write_record=write_record,
        forward_record=forward_record,
        ensure_flushed=ensure_flushed,
    )

    record = pb.Record()
    fc.send_with_flow_control(record)
