"""Unit tests for Weave media adapter helpers."""

from __future__ import annotations

import pytest
import wandb
from wandb.integration.weave.media_adapters import unwrap_value


def test_media_adapter_image_value_unwrapped_to_pil():
    from PIL import Image as PILImage

    pil_in = PILImage.new("RGB", (2, 2), color="red")
    image = wandb.Image(pil_in)

    with pytest.warns(UserWarning, match="wandb.Image values"):
        result = unwrap_value(image, "img", set())

    assert isinstance(result, PILImage.Image)
    assert result.size == (2, 2)


def test_media_adapter_rejects_external_image_reference():
    image = wandb.Image("https://example.com/image.png")

    with (
        pytest.warns(UserWarning, match="wandb.Image values"),
        pytest.raises(
            TypeError,
            match="Unsupported external media reference",
        ),
    ):
        unwrap_value(image, "img", set())


def test_media_adapter_rejects_unsupported_wandb_media():
    html = wandb.Html("<p>hi</p>")

    with pytest.raises(TypeError) as exc_info:
        unwrap_value(html, "html", set())

    message = str(exc_info.value)
    assert "unsupported wandb media type 'Html'" in message
    assert "Only wandb.Image is currently supported" in message


def test_media_adapter_rejects_unsupported_wandb_value():
    histogram = wandb.Histogram([1, 2, 3])

    with pytest.raises(TypeError) as exc_info:
        unwrap_value(histogram, "histogram", set())

    message = str(exc_info.value)
    assert "unsupported wandb value type 'Histogram'" in message
    assert "Only wandb.Image is currently supported" in message


def test_media_adapter_stubs_unsupported_wandb_media():
    html = wandb.Html("<p>hi</p>", inject=False)
    assert html._sha256 is not None
    expected_stub = f"[wandb.Html unsupported: {html._sha256[:8]}]"

    with pytest.warns(UserWarning, match="wandb.Html values are not supported"):
        result = unwrap_value(
            html,
            "html",
            set(),
            unsupported_media_mode="stub",
        )

    assert result == expected_stub


def test_media_adapter_stubs_unsupported_wandb_value_without_natural_hash():
    histogram = wandb.Histogram([1, 2, 3])

    with pytest.warns(UserWarning, match="wandb.Histogram values are not supported"):
        result = unwrap_value(
            histogram,
            "histogram",
            set(),
            unsupported_media_mode="stub",
        )

    assert result.startswith("[wandb.Histogram unsupported: ")
    assert result.endswith("]")
    digest = result.removeprefix("[wandb.Histogram unsupported: ").removesuffix("]")
    assert len(digest) == 8


def test_media_adapter_rejects_unknown_unsupported_media_mode():
    with pytest.raises(ValueError, match="unsupported_media_mode"):
        unwrap_value("plain text", "text", set(), unsupported_media_mode="ignore")
