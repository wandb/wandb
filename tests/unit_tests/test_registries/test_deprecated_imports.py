"""Tests for deprecated registries import paths.

This module tests backward compatibility for the deprecated
`wandb.apis.public.registries` import path.

These tests can be removed when the deprecated import path is removed.
"""

from __future__ import annotations

import warnings


class TestDeprecatedRegistriesImports:
    """Tests that deprecated import paths work and emit warnings."""

    def test_legacy_registry_import_emits_warning(self) -> None:
        """Importing Registry from deprecated path emits DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # This import should emit a deprecation warning
            from wandb.apis.public.registries import (  # noqa: F401
                Registry as LegacyRegistry,
            )

            # Should have at least one deprecation warning
            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1

            # Check the warning message
            assert any(
                "wandb.apis.public.registries" in str(warning.message)
                and "wandb.registries" in str(warning.message)
                for warning in deprecation_warnings
            )

    def test_legacy_and_new_imports_are_same_objects(self) -> None:
        """Legacy and new import paths return the same class objects."""
        # Suppress warnings for this test
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)

            from wandb.apis.public.registries import Registries as LegacyRegistries
            from wandb.apis.public.registries import Registry as LegacyRegistry
            from wandb.registries import Registries, Registry

            assert LegacyRegistry is Registry
            assert LegacyRegistries is Registries

    def test_public_api_import_no_warning(self) -> None:
        """Importing from wandb.apis.public should NOT emit a warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # This import should NOT emit a deprecation warning
            from wandb.apis.public import Registries, Registry  # noqa: F401

            # Filter for deprecation warnings specifically about registries
            registries_warnings = [
                x
                for x in w
                if issubclass(x.category, DeprecationWarning)
                and "registries" in str(x.message).lower()
            ]
            assert len(registries_warnings) == 0
