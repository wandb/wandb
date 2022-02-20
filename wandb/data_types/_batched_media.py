from typing import Sequence, Type, TYPE_CHECKING, Union
from _media import Media

if TYPE_CHECKING:
    from wandb_run import Run


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
