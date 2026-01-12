from __future__ import annotations

import pytest
from wandb.errors import Error
from wandb.errors.util import ProtobufErrorHandler
from wandb.proto import wandb_internal_pb2 as pb


@pytest.mark.parametrize(
    "error, expected",
    [
        (pb.ErrorInfo(), type(None)),
        (pb.ErrorInfo(code=-2), Error),
    ],
)
def test_protobuf_error_handler(error, expected):
    exc = ProtobufErrorHandler.to_exception(error)
    assert isinstance(exc, expected)


def test_protobuf_error_handler_exception():
    with pytest.raises(TypeError):
        ProtobufErrorHandler.from_exception(Exception(""))  # type: ignore
