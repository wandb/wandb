"""Tests for deprecated registries import paths.

This module tests backward compatibility for the deprecated
`wandb.apis.public.registries` import path.

These tests can be removed when the deprecated import path is removed.
"""

from __future__ import annotations

from pytest import mark, warns


def test_legacy_registry_import_emits_warning() -> None:
    """Importing Registry from deprecated path emits DeprecationWarning."""
    with warns(DeprecationWarning):
        from wandb.apis.public.registries import (
            Registry as LegacyRegistry,  # noqa: F401
        )


@mark.filterwarnings("ignore:.*registries.*:DeprecationWarning")
def test_legacy_and_new_imports_are_same_objects() -> None:
    """Legacy and new import paths return the same class objects."""
    from wandb.apis.public.registries import Registry as LegacyRegistry
    from wandb.registries import Registry

    assert LegacyRegistry is Registry


@mark.filterwarnings("error:.*registries.*:DeprecationWarning")
def test_public_api_import_no_warning() -> None:
    """Importing from wandb.apis.public should NOT emit a warning."""
    from wandb.apis.public import Registries, Registry  # noqa: F401


@mark.filterwarnings("error:.*registries.*:DeprecationWarning")
def test_importing_apis_public_registries_module_emits_no_warning() -> None:
    """Importing `wandb.apis.public.registries`, while discouraged, should NOT emit a warning."""
    import wandb.apis.public.registries  # noqa: F401
    from wandb.apis.public import registries  # noqa: F401

    # NOTE: Explicitly testing these imports since the `Registries/Collections/Versions`
    # paginators need to be imported internally, and should NOT emit warnings.
    from wandb.apis.public.registries import (
        Collections,  # noqa: F401
        Registries,  # noqa: F401
        Versions,  # noqa: F401
    )
