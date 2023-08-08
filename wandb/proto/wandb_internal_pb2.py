import os
import sys
import google.protobuf

protobuf_version = google.protobuf.__version__[0]

# Add protodir into path to resolve relative imports
proto_dir = os.path.abspath(os.path.dirname(__file__))
if proto_dir not in sys.path:
    sys.path.insert(1, proto_dir)

if protobuf_version == "3":
    from wandb.proto.v3.wandb_internal_pb2 import *
elif protobuf_version == "4":
    from wandb.proto.v4.wandb_internal_pb2 import *
