class Video(BatchableMedia):

    """
        Wandb representation of video.

        Arguments:
            data_or_path (numpy array, string, io):
                Video can be initialized with a path to a file or an io object.
                    The format must be "gif", "mp4", "webm" or "ogg".
                    The format must be specified with the format argument.
                Video can be initialized with a numpy tensor.
                    The numpy tensor must be either 4 dimensional or 5 dimensional.
                    Channels should be (time, channel, height, width) or
                        (batch, time, channel, height width)
            caption (string): caption associated with the video for display
            fps (int): frames per second for video. Default is 4.
            format (string): format of video, necessary if initializing with path or io object.
    """

    EXTS = ("gif", "mp4", "webm", "ogg")

    def __init__(self, data_or_path, caption=None, fps=4, format=None):
        super(Video, self).__init__()

        self._fps = fps
        self._format = format or "gif"
        self._width = None
        self._height = None
        self._channels = None
        self._caption = caption
        if self._format not in Video.EXTS:
            raise ValueError("wandb.Video accepts %s formats" % ", ".join(Video.EXTS))

        if isinstance(data_or_path, six.BytesIO):
            filename = os.path.join(
                MEDIA_TMP.name, util.generate_id() + "." + self._format
            )
            with open(filename, "wb") as f:
                f.write(data_or_path.read())
            self._set_file(filename, is_tmp=True)
        elif isinstance(data_or_path, six.string_types):
            _, ext = os.path.splitext(data_or_path)
            ext = ext[1:].lower()
            if ext not in Video.EXTS:
                raise ValueError(
                    "wandb.Video accepts %s formats" % ", ".join(Video.EXTS)
                )
            self._set_file(data_or_path, is_tmp=False)
            # ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 data_or_path
        else:
            if hasattr(data_or_path, "numpy"):  # TF data eager tensors
                self.data = data_or_path.numpy()
            elif is_numpy_array(data_or_path):
                self.data = data_or_path
            else:
                raise ValueError(
                    "wandb.Video accepts a file path or numpy like data as input"
                )
            self.encode()

    def encode(self):
        mpy = util.get_module(
            "moviepy.editor",
            required='wandb.Video requires moviepy and imageio when passing raw data.  Install with "pip install moviepy imageio"',
        )
        tensor = self._prepare_video(self.data)
        _, self._height, self._width, self._channels = tensor.shape

        # encode sequence of images into gif string
        clip = mpy.ImageSequenceClip(list(tensor), fps=self._fps)

        filename = os.path.join(MEDIA_TMP.name, util.generate_id() + "." + self._format)
        try:  # older version of moviepy does not support progress_bar argument.
            if self._format == "gif":
                clip.write_gif(filename, verbose=False, progress_bar=False)
            else:
                clip.write_videofile(filename, verbose=False, progress_bar=False)
        except TypeError:
            if self._format == "gif":
                clip.write_gif(filename, verbose=False)
            else:
                clip.write_videofile(filename, verbose=False)
        self._set_file(filename, is_tmp=True)

    @classmethod
    def get_media_subdir(cls):
        return os.path.join("media", "videos")

    def to_json(self, run):
        json_dict = super(Video, self).to_json(run)
        json_dict["_type"] = "video-file"

        if self._width is not None:
            json_dict["width"] = self._width
        if self._height is not None:
            json_dict["height"] = self._height
        if self._caption:
            json_dict["caption"] = self._caption

        return json_dict

    def _prepare_video(self, V):
        """This logic was mostly taken from tensorboardX"""
        np = util.get_module(
            "numpy",
            required='wandb.Video requires numpy when passing raw data. To get it, run "pip install numpy".',
        )
        if V.ndim < 4:
            raise ValueError(
                "Video must be atleast 4 dimensions: time, channels, height, width"
            )
        if V.ndim == 4:
            V = V.reshape(1, *V.shape)
        b, t, c, h, w = V.shape

        if V.dtype != np.uint8:
            logging.warning("Converting video data to uint8")
            V = V.astype(np.uint8)

        def is_power2(num):
            return num != 0 and ((num & (num - 1)) == 0)

        # pad to nearest power of 2, all at once
        if not is_power2(V.shape[0]):
            len_addition = int(2 ** V.shape[0].bit_length() - V.shape[0])
            V = np.concatenate((V, np.zeros(shape=(len_addition, t, c, h, w))), axis=0)

        n_rows = 2 ** ((b.bit_length() - 1) // 2)
        n_cols = V.shape[0] // n_rows

        V = np.reshape(V, newshape=(n_rows, n_cols, t, c, h, w))
        V = np.transpose(V, axes=(2, 0, 4, 1, 5, 3))
        V = np.reshape(V, newshape=(t, n_rows * h, n_cols * w, c))
        return V

    @classmethod
    def seq_to_json(cls, videos, run, key, step):
        base_path = os.path.join(run.dir, cls.get_media_subdir())
        util.mkdir_exists_ok(base_path)

        meta = {
            "_type": "videos",
            "count": len(videos),
            "videos": [v.to_json(run) for v in videos],
            "captions": Video.captions(videos),
        }
        return meta

    @classmethod
    def captions(cls, videos):
        if videos[0]._caption != None:
            return [v._caption for v in videos]
        else:
            return False
