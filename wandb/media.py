import os
from wandb import util


class Media(object):
    @classmethod
    def from_type(cls, type):
        pass


class Image(object):
    def __init__(self, data, mode=None, caption=None):
        """
        Accepts numpy array of image data, or a PIL image. The class attempts to infer
        the data format and converts it.
        """
        try:
            from PIL import Image as PILImage
        except ImportError:
            raise ValueError(
                "wandb.Image requires the PIL package: pip install pillow")
        if type(data) == PILImage.Image:
            self.image = data
        else:
            self.image = PILImage.fromarray(
                self.to_uint8(data), mode=mode or self.guess_mode(data))
        self.caption = caption

    def guess_mode(self, data):
        """
        Guess what type of image the np.array is representing 
        """
        # TODO: do we want to support dimensions being at the beginning of the array?
        if data.shape[-1] == 1 or len(data.shape) == 2:
            return "L"
        elif data.shape[-1] == 3:
            return "RGB"
        elif data.shape[-1] == 4:
            return "RGBA"
        else:
            raise ValueError(
                "Un-supported shape for image conversion %s" % list(data.shape))

    def to_uint8(self, data):
        """
        Converts floating point image on the range [0,1] and integer images
        on the range [0,255] to uint8, clipping if necessary.
        """
        try:
            import numpy as np
        except ImportError:
            raise ValueError(
                "wandb.Image requires numpy if not supplying PIL Images: pip install numpy")
        if issubclass(data.dtype.type, np.floating):
            data = (data * 255).astype(np.int32)
        assert issubclass(data.dtype.type, np.integer), 'Illegal image format.'
        return data.clip(0, 255).astype(np.uint8)

    @staticmethod
    def transform(images, out_dir, fname):
        """
        Combines a list of images into a single sprite returning meta information
        """
        from PIL import Image as PILImage
        base = os.path.join(out_dir, "media", "images")
        width, height = images[0].image.size
        sprite = PILImage.new(
            mode='RGB',
            size=(width * len(images), height),
            color=(0, 0, 0, 0))
        for i, image in enumerate(images):
            location = width * i
            sprite.paste(image.image, (location, 0))
        util.mkdir_exists_ok(base)
        sprite.save(os.path.join(base, fname), transparency=0)
        meta = {"width": width, "height": height,
                "count": len(images), "_type": "images"}
        captions = Image.captions(images)
        if captions:
            meta["captions"] = captions
        return meta

    @staticmethod
    def captions(images):
        if images[0].caption:
            return [i.caption for i in images]
        else:
            return False
