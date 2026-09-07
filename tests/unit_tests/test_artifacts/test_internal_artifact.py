from pytest import mark
from wandb.sdk.artifacts._internal_artifact import (
    InternalArtifact,
    sanitize_artifact_name,
)
from wandb.sdk.artifacts._validators import NAME_MAXLEN, validate_artifact_name


@mark.parametrize(
    "name",
    [
        "my-artifact",
        "dataset_2026.table",
        "run-12345-loss",
        "a" * 128,
    ],
)
def test_sanitize_artifact_name_preserves_valid(name: str):
    """Already valid artifact names within 128 chars should be returned unchanged."""
    assert sanitize_artifact_name(name) == name


@mark.parametrize(
    "name",
    [
        "run 12345:metric/table",
        "nested/path/to/artifact",
        "special!@#$%^&*()_+chars",
    ],
)
def test_sanitize_artifact_name_sanitizes_invalid_chars(name: str):
    """Names with invalid characters should be stripped and suffixed with CRC32."""
    sanitized = sanitize_artifact_name(name)
    assert len(sanitized) <= NAME_MAXLEN
    validate_artifact_name(sanitized)
    assert "-" in sanitized


@mark.parametrize(
    "length",
    [129, 150, 200, 300, 500],
)
def test_sanitize_artifact_name_truncates_long_names(length: int):
    """Auto-generated or user-provided names longer than 128 characters must be safely bounded."""
    raw_name = "run-abcdef123456-table-metric-" + "x" * length
    sanitized = sanitize_artifact_name(raw_name)
    assert len(sanitized) <= NAME_MAXLEN
    validate_artifact_name(sanitized)
    assert sanitized.startswith("run-abcdef123456-table-metric-")


def test_sanitize_artifact_name_idempotent():
    """Sanitizing an already sanitized name should return the identical string."""
    names = [
        "already-valid-name",
        "run-12345/special table name",
        "x" * 250,
        "run-" + "a" * 150 + "-incr-table",
    ]
    for name in names:
        first = sanitize_artifact_name(name)
        second = sanitize_artifact_name(first)
        assert first == second


def test_sanitize_artifact_name_uniqueness_on_long_names():
    """Two long names differing only in the middle or end produce different sanitized outputs."""
    name_a = "prefix-" + "a" * 200 + "-suffix-one"
    name_b = "prefix-" + "a" * 200 + "-suffix-two"
    sanitized_a = sanitize_artifact_name(name_a)
    sanitized_b = sanitize_artifact_name(name_b)
    assert sanitized_a != sanitized_b
    assert len(sanitized_a) <= NAME_MAXLEN
    assert len(sanitized_b) <= NAME_MAXLEN


def test_internal_artifact_with_long_auto_generated_name():
    """InternalArtifact initialization succeeds even when the generated name exceeds 128 chars."""
    long_key = "very_long_metric_evaluation_dataset_key_" + "z" * 150
    artifact_name = f"run-xyz789-{long_key}"
    artifact = InternalArtifact(artifact_name, "run_table")
    assert len(artifact.name) <= NAME_MAXLEN
    validate_artifact_name(artifact.name)
