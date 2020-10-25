import os

from wandb import util


class Media(object):
    pass


class ClassSet(Media):
    def __init__(self, class_set):
        self._class_set = class_set
        # TODO: validate

    def to_json(self, artifact):
        return {"type": "class-set", "class_set": self._class_set}


class Image(Media):
    def __init__(
        self, path, boxes=None, masks=None, classes=None, present_classes=None
    ):
        if not os.path.isfile(path):
            raise ValueError("must be image path")
        self._path = path
        self._boxes = boxes
        self._masks = masks
        self._classes = classes
        self._present_classes = present_classes

    def to_json(self, artifact):
        PILImage = util.get_module(
            "PIL.Image",
            required='wandb.Image needs the PIL package. To get it, run "pip install pillow".',
        )
        name = "media/images/%s" % os.path.basename(self._path)
        image_entry = artifact.add_file(self._path, name=name)
        image = PILImage.open(self._path)
        masks = {}
        if self._masks is not None:
            for k, v in self._masks.items():
                mask_path = v["path"]
                mask_name = "media/masks/%s" % os.path.basename(mask_path)
                mask_entry = artifact.add_file(v["path"], name=mask_name)
                masks[k] = {
                    "type": "mask-file",
                    "path": mask_name,
                    "digest": mask_entry.digest,
                }
        classes_entry = artifact._manifest.entries[self._classes["path"]]

        return {
            "type": "image-file",
            "digest": image_entry.digest,
            "path": name,
            "width": image.size[0],
            "height": image.size[1],
            "boxes": self._boxes,
            "masks": masks,
            "classes": {
                "type": "classes-file",
                "path": classes_entry.path,
                "digest": classes_entry.digest,
            },
            "present_classes": {
                "type": "class-id-list",
                "values": self._present_classes,
            },
        }


class Table(Media):
    def __init__(self, cols):
        self._cols = cols
        self._data = []

    def add_data(self, *data):
        if len(data) != len(self._cols):
            raise ValueError(
                "This table expects {} columns: {}".format(len(self._cols), self._cols)
            )
        self._data.append(list(data))

    def save(self, path):
        pass

    def to_json(self, artifact):
        mapped_data = []
        for row in self._data:
            mapped_row = []
            for v in row:
                if isinstance(v, Media):
                    mapped_row.append(v.to_json(artifact))
                else:
                    mapped_row.append(v)
            mapped_data.append(mapped_row)
        json_dict = {"columns": self._cols, "data": mapped_data}
        json_dict["_type"] = "table"
        json_dict["ncols"] = len(self._cols)
        json_dict["nrows"] = len(mapped_data)
        return json_dict


class JoinedTable(Media):
    def __init__(self, table1_path, table2_path, join_key):
        self._table1_path = table1_path
        self._table2_path = table2_path
        self._join_key = join_key

    def to_json(self, artifact):
        # TODO: assert these are in artifact
        return {
            "type": "joined-table",
            "table1_path": self._table1_path,
            "table2_path": self._table2_path,
        }


# TODO: type
class LinePlot(Media):
    def __init__(self, y, x="step"):
        self._y = y
        self._x = x

    def save(self, path):
        pass

    def to_json(self, artifact):
        return {
            "_type": "line-plot",
            "y": self._y,
            "x": self._x,
        }


class PanelGroup(Media):
    def __init__(self, *items):
        self._items = items

    def to_json(self, artifact):
        return {
            "_type": "panel-group",
            "items": [i.to_json(artifact) for i in self._items],
        }
