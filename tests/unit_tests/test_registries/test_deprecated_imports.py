"""Tests for deprecated registries import paths.

This module tests backward compatibility for the deprecated
`wandb.apis.public.registries` import path.

These tests can be removed when the deprecated import path is removed.
"""

from __future__ import annotations

from pytest import WarningsRecorder, mark, warns


def test_legacy_registry_import_emits_warning() -> None:
    """Importing Registry from deprecated path emits DeprecationWarning."""
    with warns(DeprecationWarning):
        from wandb.apis.public.registries import (  # noqa: F401
            Registry as LegacyRegistry,
        )


@mark.filterwarnings("ignore:.*registries.*:DeprecationWarning")
def test_legacy_and_new_imports_are_same_objects() -> None:
    """Legacy and new import paths return the same class objects."""
    from wandb.apis.public.registries import Registry as LegacyRegistry
    from wandb.registries import Registry

    assert LegacyRegistry is Registry


@mark.filterwarnings("error:.*registries.*:DeprecationWarning")
def test_public_api_import_no_warning(recwarn: WarningsRecorder) -> None:
    """Importing from wandb.apis.public should NOT emit a warning."""
    from wandb.apis.public import Registries, Registry  # noqa: F401
