#
from enum import Enum

"""
Call run.alert() to generate an email or Slack notification programmatically.
"""


class AlertLevel(Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
