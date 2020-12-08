from wandb.sdk import wandb_run
from wandb.sdk import wandb_artifacts
from .wbvalue import WBValue


class Media(WBValue):
    """A WBValue that we store as a file outside JSON and show in a media panel
    on the front end.

    If necessary, we move or copy the file into the Run's media directory so that it gets
    uploaded.
    """

    # Staging directory so we can encode raw data into files, then hash them before
    # we put them into the Run directory to be uploaded.
    MEDIA_TMP = tempfile.TemporaryDirectory("wandb-media")

    def __init__(self, caption=None):
        super(Media, self).__init__()
        self._path = None
        # The run under which this object is bound, if any.
        self._run = None
        self._caption = caption

    def _set_file(self, path, is_tmp=False, extension=None):
        self._path = path
        self._is_tmp = is_tmp
        self._extension = extension
        if extension is not None and not path.endswith(extension):
            raise ValueError(
                'Media file extension "{}" must occur at the end of path "{}".'.format(
                    extension, path
                )
            )

        with open(self._path, "rb") as f:
            self._sha256 = hashlib.sha256(f.read()).hexdigest()
        self._size = os.path.getsize(self._path)

    @classmethod
    def get_media_subdir(cls):
        raise NotImplementedError

    @classmethod
    def captions(cls, media_items):
        if media_items[0]._caption is not None:
            return [m._caption for m in media_items]
        else:
            return False

    def is_bound(self):
        return self._run is not None

    def file_is_set(self):
        return self._path is not None

    def bind_to_run(self, run, key, step, id_=None):
        """Bind this object to a particular Run.

        Calling this function is necessary so that we have somewhere specific to
        put the file associated with this object, from which other Runs can
        refer to it.
        """
        if not self.file_is_set():
            raise AssertionError("bind_to_run called before _set_file")
        if run is None:
            raise TypeError('Argument "run" must not be None.')
        self._run = run

        base_path = os.path.join(self._run.dir, self.get_media_subdir())

        if self._extension is None:
            rootname, extension = os.path.splitext(os.path.basename(self._path))
        else:
            extension = self._extension
            rootname = os.path.basename(self._path)[: -len(extension)]

        if id_ is None:
            id_ = self._sha256[:8]

        file_path = wb_filename(key, step, id_, extension)
        media_path = os.path.join(self.get_media_subdir(), file_path)
        new_path = os.path.join(base_path, file_path)
        util.mkdir_exists_ok(os.path.dirname(new_path))

        if self._is_tmp:
            shutil.move(self._path, new_path)
            self._path = new_path
            self._is_tmp = False
            _datatypes_callback(media_path)
        else:
            shutil.copy(self._path, new_path)
            self._path = new_path
            _datatypes_callback(media_path)

    def to_json(self, run):
        """Serializes the object into a JSON blob, using a run or artifact to store additional data. If `run_or_artifact`
        is a wandb.Run then `self.bind_to_run()` must have been previously been called.

        Args:
            run_or_artifact (wandb.Run | wandb.Artifact): the Run or Artifact for which this object should be generating
            JSON for - this is useful to to store additional data if needed.

        Returns:
            dict: JSON representation
        """
        json_obj = {}
        if isinstance(run, wandb_run.Run):
            if not self.is_bound():
                raise RuntimeError(
                    "Value of type {} must be bound to a run with bind_to_run() before being serialized to JSON.".format(
                        type(self).__name__
                    )
                )

            assert (
                self._run is run
            ), "We don't support referring to media files across runs."

            json_obj.update(
                {
                    "_type": "file",  # TODO(adrian): This isn't (yet) a real media type we support on the frontend.
                    "path": util.to_forward_slash_path(
                        os.path.relpath(self._path, self._run.dir)
                    ),
                    "sha256": self._sha256,
                    "size": self._size,
                }
            )
        elif isinstance(run, wandb_artifacts.Artifact):
            if self.file_is_set():
                artifact = run
                # Checks if the concrete image has already been added to this artifact
                name = artifact.get_added_local_path_name(self._path)
                if name is None:
                    name = os.path.join(
                        self.get_media_subdir(), os.path.basename(self._path)
                    )

                    # if not, check to see if there is a source artifact for this object
                    if (
                        self.artifact_source is not None
                        and self.artifact_source["artifact"] != artifact
                    ):
                        default_root = self.artifact_source["artifact"]._default_root()
                        # if there is, get the name of the entry (this might make sense to move to a helper off artifact)
                        if self._path.startswith(default_root):
                            name = self._path[len(default_root) :]
                            name = name.lstrip(os.sep)

                        # Add this image as a reference
                        path = self.artifact_source["artifact"].get_path(name)
                        artifact.add_reference(path.ref_url(), name=name)
                    else:
                        entry = artifact.add_file(
                            self._path, name=name, is_tmp=self._is_tmp
                        )
                        name = entry.path

                json_obj["path"] = name
            json_obj["_type"] = self.artifact_type
        return json_obj


class BatchableMedia(Media):
    """Parent class for Media we treat specially in batches, like images and
    thumbnails.

    Apart from images, we just use these batches to help organize files by name
    in the media directory.
    """

    def __init__(self):
        super(BatchableMedia, self).__init__()

    @classmethod
    def seq_to_json(self, seq, run, key, step):
        raise NotImplementedError
