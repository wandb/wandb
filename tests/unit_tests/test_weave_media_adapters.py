"""Unit tests for Weave media adapter helpers."""

from __future__ import annotations

import pytest
import wandb
from wandb.integration.weave.media_adapters import unwrap_value


def test_media_adapter_rejects_unsupported_wandb_media():
    html = wandb.Html("<p>hi</p>")

    with pytest.raises(TypeError) as exc_info:
        unwrap_value(html, "html", unsupported_media_mode="raise")

    message = str(exc_info.value)
    assert "unsupported wandb media type 'Html'" in message
    assert "Only wandb.Image is currently supported" in message


def test_media_adapter_rejects_unsupported_wandb_value():
    histogram = wandb.Histogram([1, 2, 3])

    with pytest.raises(TypeError) as exc_info:
        unwrap_value(histogram, "histogram", unsupported_media_mode="raise")

    message = str(exc_info.value)
    assert "unsupported wandb value type 'Histogram'" in message
    assert "Only wandb.Image is currently supported" in message


def test_media_adapter_stubs_unsupported_wandb_media(mock_wandb_log):
    html = wandb.Html("<p>hi</p>", inject=False)

    result = unwrap_value(
        html,
        "html",
        unsupported_media_mode="stub",
    )

    mock_wandb_log.assert_warned("wandb.Html values are not yet supported")
    assert result == "[wandb.Html not yet supported]"


def test_media_adapter_stubs_same_wandb_type_consistently(mock_wandb_log):
    html = wandb.Html("<p>hi</p>", inject=False)
    same_html = wandb.Html("<p>hi</p>", inject=False)
    different_html = wandb.Html("<p>bye</p>", inject=False)

    result = unwrap_value(
        html,
        "html",
        unsupported_media_mode="stub",
    )
    same_result = unwrap_value(
        same_html,
        "html",
        unsupported_media_mode="stub",
    )
    different_result = unwrap_value(
        different_html,
        "html",
        unsupported_media_mode="stub",
    )

    mock_wandb_log.assert_warned("wandb.Html values are not yet supported")
    assert result == same_result
    assert result == different_result


def test_media_adapter_stubs_unsupported_wandb_value_without_natural_hash(
    mock_wandb_log,
):
    histogram = wandb.Histogram([1, 2, 3])

    result = unwrap_value(
        histogram,
        "histogram",
        unsupported_media_mode="stub",
    )

    mock_wandb_log.assert_warned("wandb.Histogram values are not yet supported")
    assert result == "[wandb.Histogram not yet supported]"


def test_media_adapter_image_value_unwrapped_to_pil(mock_wandb_log):
    from PIL import Image as PILImage

    pil_in = PILImage.new("RGB", (2, 2), color="red")
    image = wandb.Image(pil_in)

    result = unwrap_value(image, "img", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Image values")
    assert isinstance(result, PILImage.Image)
    assert result.size == (2, 2)


def test_media_adapter_image_path_unwrapped_to_pil(tmp_path, mock_wandb_log):
    from PIL import Image as PILImage

    image_path = tmp_path / "image.png"
    PILImage.new("RGB", (3, 4), color="red").save(image_path)
    image = wandb.Image(str(image_path))

    result = unwrap_value(image, "img", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Image values")
    assert isinstance(result, PILImage.Image)
    assert result.size == (3, 4)


def test_media_adapter_rejects_external_image_reference(mock_wandb_log):
    image = wandb.Image("https://example.com/image.png")

    with pytest.raises(
        TypeError,
        match="Unsupported external media reference",
    ):
        unwrap_value(image, "img", unsupported_media_mode="raise")

    mock_wandb_log.assert_warned("wandb.Image values")
