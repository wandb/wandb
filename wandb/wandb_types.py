import base64
import io
import collections

class Percentage(object):
    typestring = 'percentage'

    def __init__(self, obj):
        if obj < 0.0 or obj > 1.0:
            raise ValueError('Percentage expects values between 0 and 1, got %i', obj)
        self._data = obj

    def encode(self):
        return self._data

class Histogram(object):
    typestring = 'histogram'

    def __init__(self, obj):
        if not isinstance(obj, collections.Iterable):
            raise ValueError('Histogram expects lists of numbers')

        self._data = obj

    def encode(self):
        return self._data



class Image(object):
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
