from __future__ import annotations

import wandb
from PIL import Image as PILImage
from wandb.sdk.data_types import _eval_table_media_ces


def test_ces_eval_table_has_no_supported_media_types():
    image = wandb.Image(PILImage.new("RGB", (1, 1)))

    assert not _eval_table_media_ces.is_supported_wandb_media(image)
