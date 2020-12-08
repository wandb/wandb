# Allows encoding of arbitrary JSON structures
# as a file
#
# This class should be used as an abstract class
# extended to have validation methods


class JSONMetadata(Media):
    """
    JSONMetadata is a type for encoding arbitrary metadata as files.
    """

    def __init__(self, val, **kwargs):
        super(JSONMetadata, self).__init__()

        self.validate(val)
        self._val = val

        ext = "." + self.type_name() + ".json"
        tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ext)
        util.json_dump_uncompressed(
            self._val, codecs.open(tmp_path, "w", encoding="utf-8")
        )
        self._set_file(tmp_path, is_tmp=True, extension=ext)

    def get_media_subdir(self):
        return os.path.join("media", "metadata", self.type_name())

    def to_json(self, run):
        json_dict = super(JSONMetadata, self).to_json(run)
        json_dict["_type"] = self.type_name()

        return json_dict

    # These methods should be overridden in the child class
    def type_name(self):
        return "metadata"

    def validate(self, val):
        return True
