from typing import Optional

from wandb.proto import wandb_internal_pb2 as pb

from . import AuthenticationError, CommError, Error, UnsupportedError, UsageError

to_exception_map = {
    pb.ErrorInfo.UNKNOWN: Error,
    pb.ErrorInfo.COMMUNICATION: CommError,
    pb.ErrorInfo.AUTHENTICATION: AuthenticationError,
    pb.ErrorInfo.USAGE: UsageError,
    pb.ErrorInfo.UNSUPPORTED: UnsupportedError,
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
    def from_exception(cls, exc: Error) -> "pb.ErrorInfo":
        """Convert an wandb error to a protobuf error message.

        Args:
            exc: The exception to convert.

        Returns:
            The corresponding protobuf error message.
        """
        if not isinstance(exc, Error):
            raise TypeError("exc must be a subclass of wandb.errors.Error")

        code = None
        for subclass in type(exc).__mro__:
            if subclass in from_exception_map:
                code = from_exception_map[subclass]  # type: ignore
                break
        return pb.ErrorInfo(code=code, message=str(exc))  # type: ignore
