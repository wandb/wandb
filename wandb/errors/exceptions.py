from . import Error

### Errors caused by the Server ###

class ServerError(Error):
    """Raised when the backend returns an error."""
    pass


class ServerTransientError(ServerError):
    """Raised when the backend returns an error that can be retried."""
    pass

class ServerUnavailableError(ServerTransientError):
    """Raised when the backend returns a server unavailable error."""
    pass

class ServerTimeoutError(ServerTransientError):
    """Raised when the backend returns a timeout error."""
    pass

class ServerRateLimitError(ServerTransientError):
    """Raised when the backend returns a rate limit error."""
    pass

class ServerPermanentError(ServerError):
    """Raised when the backend returns an error that cannot be retried."""
    pass


### Errors caused by the Internal SDK logic ###


class InternalError(Error):
    """Raised when an internal error occurs."""
    pass


class MailboxError(InternalError):
    """Generic Mailbox Exception"""

    pass

class ContextCancelledError(MailboxError):
    """Context cancelled Exception"""

    pass



class ServiceError(InternalError):
    """Generic Service Exception"""

    pass


class ServiceStartProcessError(ServiceError):
    """Raised when a known error occurs when launching wandb service"""

    pass


class ServiceStartTimeoutError(ServiceError):
    """Raised when service start times out"""

    pass


class ServiceStartPortError(ServiceError):
    """Raised when service start fails to find a port"""

    pass


### Errors caused by the user ###


class UserError(Error):
    """Raised when a user error occurs."""
    pass

class UsageError(UserError):
    """Raised when a usage error occurs."""
    pass

class Abort(Error):
    """Raised when critical errors occur."""
    pass

