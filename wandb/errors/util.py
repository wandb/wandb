from typing import Optional

from wandb.proto import wandb_internal_pb2 as pb

from . import (
    AuthenticationError,
    AuthorizationError,
    Error,
    InvalidError,
    PermissionsError,
)

to_exception_map = {
    pb.ErrorInfo.UNKNOWN: Error,
    pb.ErrorInfo.INVALID: InvalidError,
    pb.ErrorInfo.PERMISSION: PermissionsError,
    pb.ErrorInfo.AUTHENTICATION: AuthenticationError,
    pb.ErrorInfo.AUTHORIZATION: AuthorizationError,
}

from_exception_map = {v: k for k, v in to_exception_map.items()}


class ProtobufErrorHandler:
    """Converts protobuf errors to exceptions and vice versa."""

    @staticmethod
    def to_exception(error: pb.ErrorInfo) -> Optional[Error]:
        """Convert a protobuf error to an exception.

        Args:
            error: The protobuf error to convert.

        Returns:
            The corresponding exception.

        """
        if not error.SerializeToString():
            return None

        if error.code in to_exception_map:
            return to_exception_map[error.code](error.message)
        return Error(error.message)

    @classmethod
    def from_exception(cls, exc: Exception) -> "pb.ErrorInfo":
        """Convert an exception to a protobuf error.

        Args:
            exc: The exception to convert.

        Returns:
            The corresponding protobuf error.
        """

        code = from_exception_map.get(type(exc), pb.ErrorInfo.UNKNOWN)
        return pb.ErrorInfo(code=code, message=str(exc))
