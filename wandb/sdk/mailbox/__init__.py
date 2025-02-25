"""A message protocol for the internal service process.

The core of W&B is implemented by a side process that asynchronously uploads
data. The client process (such as this Python code) sends requests to the
service, and for some requests, the service eventually sends a response.

The client can send multiple requests before the service provides a response.
The Mailbox handles matching responses to requests. An internal thread
continuously reads data from the service and passes it to the mailbox.
"""

from .mailbox import Mailbox, MailboxClosedError
from .mailbox_handle import HandleAbandonedError, MailboxHandle
from .wait_with_progress import wait_all_with_progress, wait_with_progress

__all__ = [
    "Mailbox",
    "MailboxClosedError",
    "HandleAbandonedError",
    "MailboxHandle",
    "wait_all_with_progress",
    "wait_with_progress",
]
