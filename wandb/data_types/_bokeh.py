import codecs
import json
import os

from _media import Media
from wandb.sdk.interface import _dtypes
from wandb.util import generate_id, get_module, json_dump_safer


class Bokeh(Media):
    """
    Wandb class for Bokeh plots.

    Arguments:
        val: Bokeh plot
    """

    _log_type = "bokeh-file"

    def __init__(self, data_or_path):
        super(Bokeh, self).__init__()
        bokeh = get_module("bokeh", required=True)
        if isinstance(data_or_path, str) and os.path.exists(data_or_path):
            with open(data_or_path, "r") as file:
                b_json = json.load(file)
            self.b_obj = bokeh.document.Document.from_json(b_json)
            self._set_file(data_or_path, is_tmp=False, extension=".bokeh.json")
        elif isinstance(data_or_path, bokeh.model.Model):
            _data = bokeh.document.Document()
            _data.add_root(data_or_path)
            # serialize/deserialize pairing followed by sorting attributes ensures
            # that the file's shas are equivalent in subsequent calls
            self.b_obj = bokeh.document.Document.from_json(_data.to_json())
            b_json = self.b_obj.to_json()
            if "references" in b_json["roots"]:
                b_json["roots"]["references"].sort(key=lambda x: x["id"])

            tmp_path = os.path.join(self._MEDIA_TMP.name, generate_id() + ".bokeh.json")
            with codecs.open(tmp_path, "w", encoding="utf-8") as fp:
                json_dump_safer(b_json, fp)
            self._set_file(tmp_path, is_tmp=True, extension=".bokeh.json")
        elif not isinstance(data_or_path, bokeh.document.Document):
            raise TypeError(
                "Bokeh constructor accepts Bokeh document/model or path to Bokeh json file"
            )

    def get_media_subdir(self):
        return os.path.join("media", "bokeh")

    def to_json(self, run):
        # TODO: (tss) this is getting redundant for all the media objects. We can probably
        # pull this into Media#to_json and remove this type override for all the media types.
        # There are only a few cases where the type is different between artifacts and runs.
        json_dict = super(Bokeh, self).to_json(run)
        json_dict["_type"] = self._log_type
        return json_dict

    @classmethod
    def from_json(cls, json_obj, source_artifact):
        return cls(source_artifact.get_path(json_obj["path"]).download())


class _BokehFileType(_dtypes.Type):
    name = "bokeh-file"
    types = [Bokeh]


_dtypes.TypeRegistry.add(_BokehFileType)
