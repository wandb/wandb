from wandb.proto import wandb_internal_pb2 as pb
from . import Error, CommError

class TimeoutError(CommError):
    """Raised when a connection times out"""

class PermissionError(CommError):
    """Raised when tries to access a resource that without sufficient permissions"""

class AuthenticationError(CommError):
    """Raised when fails to provide valid authentication credentials"""

class AuthorizationError(CommError):
    """Raised when not authorized to access a particular resource"""

class RateLimitError(CommError):
    """Raised when there is a rate limit error"""


to_exception_map = {
    pb.ErrorInfo.UNKNOWN: Error,
    pb.ErrorInfo.PERMISSION: PermissionError,
    pb.ErrorInfo.AUTHENTICATION: AuthenticationError,
    pb.ErrorInfo.AUTHORIZATION: AuthorizationError,
    pb.ErrorInfo.RATELIMIT: RateLimitError,
}

from_exception_map = {v: k for k, v in to_exception_map.items()}

class ProtobufErrorHandler:
    """Converts protobuf errors to exceptions and vice versa."""

    @staticmethod
    def to_exception(error: pb.ErrorInfo) -> Exception:
        """Convert a protobuf error to an exception.
        
        Args:
            error: The protobuf error to convert.
            
        Returns:
            The corresponding exception.
        
        """

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

        code = from_exception_map.get(exc, pb.ErrorInfo.UNKNOWN)
        return pb.ErrorInfo(code=code, message=str(exc))
    