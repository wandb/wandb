"""Errors shared by the schedulers that drive sweeps."""


class SweepNotFoundError(Exception):
    """Raised when a sweep is not found, typically because it was deleted."""
