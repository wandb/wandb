import logging
import os
from io import BytesIO
from typing import TYPE_CHECKING, Any, Dict, Optional, Sequence, Type, Union

from wandb import util
from wandb.sdk.lib import filesystem, runid

from . import _dtypes
from ._private import MEDIA_TMP
from .base_types.media import BatchableMedia

if TYPE_CHECKING:  # pragma: no cover
    from typing import TextIO

    import numpy as np

    from wandb.sdk.artifacts.artifact import Artifact

    from ..wandb_run import Run as LocalRun


# This helper function is a workaround for the issue discussed here:
# https://github.com/wandb/wandb/issues/3472
#
# Essentially, the issue is that moviepy's write_gif function fails to close
# the open write / file descriptor returned from `imageio.save`. The following
# function is a simplified copy of the function in the moviepy source code.
# See https://github.com/Zulko/moviepy/blob/7e3e8bb1b739eb6d1c0784b0cb2594b587b93b39/moviepy/video/io/gif_writers.py#L428
#
# Except, we close the writer!
def write_gif_with_image_io(
    clip: Any, filename: str, fps: Optional[int] = None
) -> None:
    imageio = util.get_module(
        "imageio",
        required='wandb.Video requires imageio when passing raw data. Install with "pip install imageio"',
    )

    writer = imageio.save(filename, fps=clip.fps, quantizer=0, palettesize=256, loop=0)

    for frame in clip.iter_frames(fps=fps, dtype="uint8"):
        writer.append_data(frame)

    writer.close()


class Video(BatchableMedia):
    """Format a video for logging to W&B.

    Arguments:
        data_or_path: (numpy array, string, io)
            Video can be initialized with a path to a file or an io object.
            The format must be "gif", "mp4", "webm" or "ogg".
            The format must be specified with the format argument.
            Video can be initialized with a numpy tensor.
            The numpy tensor must be either 4 dimensional or 5 dimensional.
            Channels should be (time, channel, height, width) or
            (batch, time, channel, height width)
        caption: (string) caption associated with the video for display
        fps: (int) frames per second for video. Default is 4.
        format: (string) format of video, necessary if initializing with path or io object.

    Examples:
        ### Log a numpy array as a video
        <!--yeadoc-test:log-video-numpy-->
        ```python
        import numpy as np
        import wandb

        wandb.init()
        # axes are (time, channel, height, width)
        frames = np.random.randint(low=0, high=256, size=(10, 3, 100, 100), dtype=np.uint8)
        wandb.log({"video": wandb.Video(frames, fps=4)})
        ```
    """

    _log_type = "video-file"
    EXTS = ("gif", "mp4", "webm", "ogg")
    _width: Optional[int]
    _height: Optional[int]

    def __init__(
        self,
        data_or_path: Union["np.ndarray", str, "TextIO", "BytesIO"],
        caption: Optional[str] = None,
        fps: int = 4,
        format: Optional[str] = None,
    ):
        super().__init__()

        self._fps = fps
        self._format = format or "gif"
        self._width = None
        self._height = None
        self._channels = None
        self._caption = caption
        if self._format not in Video.EXTS:
            raise ValueError(
                "wandb.Video accepts {} formats".format(", ".join(Video.EXTS))
            )

        if isinstance(data_or_path, BytesIO):
            filename = os.path.join(
                MEDIA_TMP.name, runid.generate_id() + "." + self._format
            )
            with open(filename, "wb") as f:
                f.write(data_or_path.read())
            self._set_file(filename, is_tmp=True)
        elif isinstance(data_or_path, str):
            _, ext = os.path.splitext(data_or_path)
            ext = ext[1:].lower()
            if ext not in Video.EXTS:
                raise ValueError(
                    "wandb.Video accepts {} formats".format(", ".join(Video.EXTS))
                )
            self._set_file(data_or_path, is_tmp=False)
            # ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 data_or_path
        else:
            if hasattr(data_or_path, "numpy"):  # TF data eager tensors
                self.data = data_or_path.numpy()
            elif util.is_numpy_array(data_or_path):
                self.data = data_or_path
            else:
                raise ValueError(
                    "wandb.Video accepts a file path or numpy like data as input"
                )
            self.encode()

    def encode(self) -> None:
        mpy = util.get_module(
            "moviepy.editor",
            required='wandb.Video requires moviepy and imageio when passing raw data.  Install with "pip install moviepy imageio"',
        )
        tensor = self._prepare_video(self.data)
        _, self._height, self._width, self._channels = tensor.shape  # type: ignore

        # encode sequence of images into gif string
        clip = mpy.ImageSequenceClip(list(tensor), fps=self._fps)

        filename = os.path.join(
            MEDIA_TMP.name, runid.generate_id() + "." + self._format
        )
        if TYPE_CHECKING:
            kwargs: Dict[str, Optional[bool]] = {}
        try:  # older versions of moviepy do not support logger argument
            kwargs = {"logger": None}
            if self._format == "gif":
                write_gif_with_image_io(clip, filename)
            else:
                clip.write_videofile(filename, **kwargs)
        except TypeError:
            try:  # even older versions of moviepy do not support progress_bar argument
                kwargs = {"verbose": False, "progress_bar": False}
                if self._format == "gif":
                    clip.write_gif(filename, **kwargs)
                else:
                    clip.write_videofile(filename, **kwargs)
            except TypeError:
                kwargs = {
                    "verbose": False,
                }
                if self._format == "gif":
                    clip.write_gif(filename, **kwargs)
                else:
                    clip.write_videofile(filename, **kwargs)
        self._set_file(filename, is_tmp=True)

    @classmethod
    def get_media_subdir(cls: Type["Video"]) -> str:
        return os.path.join("media", "videos")

    def to_json(self, run_or_artifact: Union["LocalRun", "Artifact"]) -> dict:
        json_dict = super().to_json(run_or_artifact)
        json_dict["_type"] = self._log_type

        if self._width is not None:
            json_dict["width"] = self._width
        if self._height is not None:
            json_dict["height"] = self._height
        if self._caption:
            json_dict["caption"] = self._caption

        return json_dict

    def _prepare_video(self, video: "np.ndarray") -> "np.ndarray":
        """This logic was mostly taken from tensorboardX."""
        np = util.get_module(
            "numpy",
            required='wandb.Video requires numpy when passing raw data. To get it, run "pip install numpy".',
        )
        if video.ndim < 4:
            raise ValueError(
                "Video must be atleast 4 dimensions: time, channels, height, width"
            )
        if video.ndim == 4:
            video = video.reshape(1, *video.shape)
        b, t, c, h, w = video.shape

        if video.dtype != np.uint8:
            logging.warning("Converting video data to uint8")
            video = video.astype(np.uint8)

        def is_power2(num: int) -> bool:
            return num != 0 and ((num & (num - 1)) == 0)

        # pad to nearest power of 2, all at once
        if not is_power2(video.shape[0]):
            len_addition = int(2 ** video.shape[0].bit_length() - video.shape[0])
            video = np.concatenate(
                (video, np.zeros(shape=(len_addition, t, c, h, w))), axis=0
            )

        n_rows = 2 ** ((b.bit_length() - 1) // 2)
        n_cols = video.shape[0] // n_rows

        video = video.reshape(n_rows, n_cols, t, c, h, w)
        video = np.transpose(video, axes=(2, 0, 4, 1, 5, 3))
        video = video.reshape(t, n_rows * h, n_cols * w, c)
        return video

    @classmethod
    def seq_to_json(
        cls: Type["Video"],
        seq: Sequence["BatchableMedia"],
        run: "LocalRun",
        key: str,
        step: Union[int, str],
    ) -> dict:
        base_path = os.path.join(run.dir, cls.get_media_subdir())
        filesystem.mkdir_exists_ok(base_path)

        meta = {
            "_type": "videos",
            "count": len(seq),
            "videos": [v.to_json(run) for v in seq],
            "captions": Video.captions(seq),
        }
        return meta


class _VideoFileType(_dtypes.Type):
    name = "video-file"
    types = [Video]


_dtypes.TypeRegistry.add(_VideoFileType)
