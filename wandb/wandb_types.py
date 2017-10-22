import base64
import io


class WandbType(object):
    def encode(self):
        return {
            'type': self.typestring,
            'val': self._encode()
        }


class Image(WandbType):
    typestring = 'b64image'

    def __init__(self, obj):
        try:
            self._data = obj.read()
        except AttributeError:
            if isinstance(obj, bytes):
                self._data = obj
            elif isinstance(obj, str):
                self._data = open(obj, 'rb').read()
            else:
                raise ValueError(
                    '%s expects bytes or file-like or file path.' % self.__class__)

    def encode(self):
        return base64.b64encode(self._data)
