import collections
import json
import os
import time
import numpy as np
from threading import Lock

import wandb
from wandb import util

global_start_time = time.time()


def convert_to_uint8(imgs):
    """
    Converts floating point image on the range [0,1] and integer images
    on the range [0,255] to uint8, clipping if necessary.
    """
    if issubclass(imgs.dtype.type, np.floating):
        imgs = (imgs * 255).astype(np.int32)
    assert issubclass(imgs.dtype.type, np.integer), 'Illegal image format.'
    return imgs.clip(0, 255).astype(np.uint8)


def convert_to_3_color_channels(imgs):
    """Final dimension should be 3 for three color channels."""
    if imgs.shape[-1] == 3:
        return imgs
    elif imgs.shape[-1] == 1:
        return convert_to_3_color_channels(imgs.reshape(imgs.shape[:-1]))
    else:
        imgs = np.array([imgs, imgs, imgs])
        if len(imgs.shape) == 3:
            return imgs.transpose((1, 2, 0))
        elif len(imgs.shape) == 4:
            return imgs.transpose((1, 2, 3, 0))
    raise RuntimeError(
        'Array shape cannot be displayed as an image {}.'.format(imgs.shape))


def save_sprite(images, fname):
    """images should are different shaped np arrays of image data"""
    from PIL import Image
    images = convert_to_3_color_channels(convert_to_uint8(images))
    width, height, colors = images[0].shape
    sprite = Image.new(
        mode='RGBA',
        size=(width * len(images), height),
        color=(0, 0, 0, 0))
    for i, image in enumerate(images):
        location = width * i
        sprite.paste(Image.fromarray(image), (location, 0))
    sprite.save(fname, transparency=0)
    return (width, height)


class JsonlFile(object):
    """Used to store data that changes over time during runs. """

    def __init__(self, fname, out_dir='.', add_callback=None):
        self._start_time = global_start_time
        self.out_dir = out_dir
        self.fname = os.path.join(out_dir, fname)
        self.rows = []
        self.row = {}
        self.last_step = 0
        try:
            with open(self.fname) as f:
                for line in f:
                    self.rows.append(json.loads(line))
        except IOError:
            pass

        self._file = open(self.fname, 'w')
        self._add_callback = add_callback

    def keys(self):
        if self.rows:
            return self.rows[0].keys()
        return []

    def column(self, key):
        return [r[key] for r in self.rows]

    def add(self, row, step=None, tag=None):
        if not isinstance(row, collections.Mapping):
            raise wandb.Error('history.add expects dict-like object')
        row['_runtime'] = round(time.time() - self._start_time, 2)
        if self.row and step == None:
            self.commit()
        self.row.update(row)
        if step != self.last_step:
            self.commit()
        if step != None:
            self.last_step = step

    def _add_media(self, media):
        self.row["_media"] = self.row.get("_media", [])
        self.row["_media"].append(media)

    def add_images(self, np_array, captions=[], tag=None, step=None):
        util.mkdir_exists_ok(os.path.join(self.out_dir, "images"))
        width, height = save_sprite(np_array, os.path.join(
            self.out_dir, "images", tag or "", "step-%s.jpg" % len(self.rows)))
        meta = {"width": width, "height": height,
                "count": len(np_array), "_type": "images"}
        if captions:
            meta["captions"] = captions
        if tag:
            meta["_tag"] = tag
        if step != self.last_step:
            self.commit()
        self._add_media(meta)
        return len(np_array)

    def commit(self):
        if self.row:
            self.row["_step"] = self.last_step
            self.rows.append(self.row)
            self._file.write(util.json_dumps_safer(self.row))
            self._file.write('\n')
            self._file.flush()
            if self._add_callback:
                self._add_callback(self.row)
            self.last_step += 1
            self.row = {}

    def close(self):
        self.commit()
        self._file.close()
        self._file = None


class JsonlEventsFile(object):
    """Used to store events during a run. """

    def __init__(self, fname, out_dir='.'):
        self._start_time = global_start_time
        self.fname = os.path.join(out_dir, fname)
        self._file = open(self.fname, 'w')
        self.buffer = []
        self.lock = Lock()

    def flatten(self, dictionary):
        if type(dictionary) == dict:
            for k, v in list(dictionary.items()):
                if type(v) == dict:
                    self.flatten(v)
                    dictionary.pop(k)
                    for k2, v2 in v.items():
                        dictionary[k + "." + k2] = v2

    def track(self, event, properties, timestamp=None, _wandb=False):
        if not isinstance(properties, collections.Mapping):
            raise wandb.Error('event.track expects dict-like object')
        self.lock.acquire()
        try:
            row = {}
            row[event] = properties
            self.flatten(row)
            if _wandb:
                row["_wandb"] = _wandb
            row["_timestamp"] = int(timestamp or time.time())
            row['_runtime'] = int(time.time() - self._start_time)
            self._file.write(util.json_dumps_safer(row))
            self._file.write('\n')
            self._file.flush()
        finally:
            self.lock.release()

    def close(self):
        self.lock.acquire()
        try:
            self._file.close()
            self._file = None
        finally:
            self.lock.release()
