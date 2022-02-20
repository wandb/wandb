import logging
from typing import Sequence, Type, TYPE_CHECKING, Union

from ._media import Media

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run


def _prune_max_seq(seq: Sequence["BatchableMedia"]) -> Sequence["BatchableMedia"]:
    # If media type has a max respect it
    items = seq
    if hasattr(seq[0], "MAX_ITEMS") and seq[0].MAX_ITEMS < len(seq):  # type: ignore
        logging.warning(
            f"Only {seq[0].MAX_ITEMS} {seq[0].__class__.__name__} will be uploaded."  # type: ignore
        )
        items = seq[: seq[0].MAX_ITEMS]  # type: ignore
    return items


class BatchableMedia(Media):
    """Parent class for Media we treat specially in batches, like images and
    thumbnails.

    Apart from images, we just use these batches to help organize files by name
    in the media directory.
    """

    def __init__(self) -> None:
        super().__init__()

    @classmethod
    def seq_to_json(
        cls: Type["BatchableMedia"],
        seq: Sequence["BatchableMedia"],
        run: "Run",
        key: str,
        step: Union[int, str],
    ) -> dict:
        raise NotImplementedError
