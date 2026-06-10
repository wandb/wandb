from __future__ import annotations

from importlib import metadata as importlib_metadata

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from wandb.errors.term import termwarn

_WARNED = False


def warn_if_unsupported_cwsandbox_version(cwsandbox_version: str) -> None:
    """Warn once if the installed cwsandbox version is outside wandb's range."""
    global _WARNED

    if _WARNED:
        return

    specifier = None
    for requirement_text in importlib_metadata.requires("wandb") or []:
        try:
            requirement = Requirement(requirement_text)
        except InvalidRequirement:
            continue
        if requirement.name == "cwsandbox":
            specifier = requirement.specifier
            break

    if not specifier:
        return

    try:
        installed_version = Version(cwsandbox_version)
    except InvalidVersion:
        return

    if installed_version in specifier:
        return

    _WARNED = True
    termwarn(
        "Installed cwsandbox-client "
        f"{cwsandbox_version} is outside the tested range "
        f"for this W&B SDK release: {specifier}. This can happen "
        "after a manual cwsandbox upgrade. The combination may work, but is "
        "not the default supported combination; reinstall `wandb[sandbox]` "
        "to return to the tested range.",
        repeat=False,
    )
