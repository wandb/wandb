import google.protobuf

protobuf_version = google.protobuf.__version__[0]

if protobuf_version == "3":
    from wandb.proto.v3.wandb_telemetry_pb2 import *
elif protobuf_version == "4":
    from wandb.proto.v4.wandb_telemetry_pb2 import *
