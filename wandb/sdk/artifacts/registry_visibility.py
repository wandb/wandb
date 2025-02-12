"""Registry visibility."""

from enum import Enum


class RegistryVisibility(Enum):
    """The visibility of a registry.

    Valid values are:
        "Organization": Anyone in the organization can view this registry. You can edit their roles later from the settings in the UI.
        "Restricted": Only invited members via the UI can access this registry. Public sharing is disabled.
    """

    ORGANIZATION = "PRIVATE"
    RESTRICTED = "RESTRICTED"
