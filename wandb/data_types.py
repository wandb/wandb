"""Wandb has special data types for logging rich visualizations.

All of the special data types are subclasses of WBValue. All of the data types
    serialize to JSON, since that is what wandb uses to save the objects locally
    and upload them to the W&B server.
"""

from __future__ import print_function

import hashlib
import itertools
import json
import pprint
import shutil
from six.moves import queue
import warnings

import numbers
import collections
import os
import io
import logging
import six
import wandb
import uuid
import json
import codecs
import tempfile
from wandb import util
from wandb.util import has_num
from wandb.compat import tempfile

# Get rid of cleanup warnings in Python 2.7.
warnings.filterwarnings('ignore', 'Implicitly cleaning up', RuntimeWarning, 'wandb.compat.tempfile')

# Staging directory so we can encode raw data into files, then hash them before
# we put them into the Run directory to be uploaded.
MEDIA_TMP = tempfile.TemporaryDirectory('wandb-media')

DATA_FRAMES_SUBDIR = os.path.join('media', 'data_frames')


class WBValue(object):
    """Abstract parent class for things that can be logged by wandb.log() and
        visualized by wandb.

    The objects will be serialized as JSON and always have a _type attribute
        that indicates how to interpret the other fields.

    Returns:
        JSON-friendly `dict` representation of this object that can later be
            serialized to a string.
    """

    def __init__(self):
        pass

    def to_json(self, run):
        """
        """
        raise NotImplementedError


class Histogram(WBValue):
    """
    wandb class for histograms

    This object works just like numpy's histogram function
    https://docs.scipy.org/doc/numpy/reference/generated/numpy.histogram.html

    Examples:
        Generate histogram from a sequence
        ```
        wandb.Histogram([1,2,3])
        ```

        Efficiently initialize from np.histogram.
        ```
        hist = np.histogram(data)
        wandb.Histogram(np_histogram=hist)
        ```

    Arguments:
        sequence (array_like): input data for histogram
        np_histogram (numpy histogram): alternative input of a precoomputed histogram
        num_bins (int): Number of bins for the histogram.  The default number of bins
            is 64.  The maximum number of bins is 512

    Attributes:
        bins ([float]): edges of bins
        histogram ([int]): number of elements falling in each bin
    """
    MAX_LENGTH = 512

    def __init__(self, sequence=None, np_histogram=None, num_bins=64):

        if np_histogram:
            if len(np_histogram) == 2:
                self.histogram = np_histogram[0].tolist() if hasattr(np_histogram[0], 'tolist') else np_histogram[0]
                self.bins = np_histogram[1].tolist() if hasattr(np_histogram[1], 'tolist') else np_histogram[1]
            else:
                raise ValueError(
                    'Expected np_histogram to be a tuple of (values, bin_edges) or sequence to be specified')
        else:
            np = util.get_module(
                "numpy", required="Auto creation of histograms requires numpy")

            self.histogram, self.bins = np.histogram(
                sequence, bins=num_bins)
            self.histogram = self.histogram.tolist()
            self.bins = self.bins.tolist()
        if len(self.histogram) > self.MAX_LENGTH:
            raise ValueError(
                "The maximum length of a histogram is %i" % self.MAX_LENGTH)
        if len(self.histogram) + 1 != len(self.bins):
            raise ValueError("len(bins) must be len(histogram) + 1")

    def to_json(self, run=None):
        return {"_type": "histogram", "values": self.histogram, "bins": self.bins}


class Media(WBValue):
    """A WBValue that we store as a file outside JSON and show in a media panel
    on the front end.

    If necessary, we move or copy the file into the Run's media directory so that it gets
    uploaded.
    """

    def __init__(self, caption=None):
        self._path = None
        # The run under which this object is bound, if any.
        self._run = None
        self._caption = caption

    def _set_file(self, path, is_tmp=False, extension=None):
        self._path = path
        self._is_tmp = is_tmp
        self._extension = extension
        if extension is not None and not path.endswith(extension):
            raise ValueError('Media file extension "{}" must occur at the end of path "{}".'.format(extension, path))

        self._sha256 = hashlib.sha256(open(self._path, 'rb').read()).hexdigest()
        self._size = os.path.getsize(self._path)

    @classmethod
    def get_media_subdir(cls):
        raise NotImplementedError

    @classmethod
    def captions(cls, media_items):
        if media_items[0]._caption != None:
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
            raise AssertionError('bind_to_run called before _set_file')
        if run is None:
            raise TypeError('Argument "run" must not be None.')
        if self.is_bound():
            raise RuntimeError('Value is already bound to a Run: {}'.format(self))
        self._run = run

        # This is a flawed way of checking whether the file is already in
        # the Run directory. It'd be better to check the actual directory
        # components.
        if not os.path.realpath(self._path).startswith(os.path.realpath(self._run.dir)):
            base_path = os.path.join(self._run.dir, self.get_media_subdir())

            if self._extension is None:
                rootname, extension = os.path.splitext(os.path.basename(self._path))
            else:
                extension = self._extension
                rootname = os.path.basename(self._path)[:-len(extension)]

            if self._is_tmp:
                if id_ is None:
                    id_ = self._sha256[:8]

                new_path = os.path.join(base_path, '{}_{}_{}{}'.format(key, step, id_, extension))
                util.mkdir_exists_ok(os.path.dirname(new_path))

                shutil.move(self._path, new_path)

                self._path = new_path
                self._is_tmp = False
            else:
                new_path = os.path.join(base_path, '{}_{}{}'.format(rootname, self._sha256[:8], extension))
                util.mkdir_exists_ok(os.path.dirname(new_path))
                shutil.copy(self._path, new_path)
                self._path = new_path

    def to_json(self, run):
        """Get the JSON-friendly dict that represents this object.

        Only works if `self.bind_to_run()` has previously been called.

        The resulting dict lets you load this object into other W&B runs.
        """
        if not self.is_bound():
            raise RuntimeError(
                'Value of type {} must be bound to a run with bind_to_run() before being serialized to JSON.'.format(type(self).__name__))

        assert self._run is run, "For now we don't support referring to media files across runs."

        return {
            '_type': 'file',  # TODO(adrian): This isn't (yet) a real media type we support on the frontend.
            'path': util.to_forward_slash_path(os.path.relpath(self._path, self._run.dir)),
            'sha256': self._sha256,
            'size': self._size,
            #'entity': self._run.entity,
            #'project': self._run.project_name(),
            #'run': self._run.name,
        }


class BatchableMedia(Media):
    """Parent class for Media we treat specially in batches, like images and
    thumbnails.

    Apart from images, we just use these batches to help organize files by name
    in the media directory.
    """
    @classmethod
    def seq_to_json(self, seq, run, key, step):
        raise NotImplementedError


class Table(Media):
    """This is a table designed to display small sets of records.

    Arguments:
        columns ([str]): Names of the columns in the table.
            Defaults to ["Input", "Output", "Expected"].
        data (array): 2D Array of values that will be displayed as strings.
    """
    MAX_ROWS = 10000

    def __init__(self, columns=["Input", "Output", "Expected"], data=None, rows=None):
        """rows is kept for legacy reasons, we use data to mimic the Pandas api
        """
        super(Table, self).__init__()
        self.columns = columns
        self.data = list(rows or data or [])

    def add_row(self, *row):
        logging.warning("add_row is deprecated, use add_data")
        self.add_data(*row)

    def add_data(self, *data):
        if len(data) != len(self.columns):
            raise ValueError("This table expects {} columns: {}".format(
                len(self.columns), self.columns))
        self.data.append(list(data))

    def _to_table_json(self):
        # seperate method for testing
        if len(self.data) > Table.MAX_ROWS:
            logging.warn("Truncating wandb.Table object to %i rows." % Table.MAX_ROWS)
        return {"columns": self.columns, "data": self.data[:Table.MAX_ROWS]}

    def bind_to_run(self, *args, **kwargs):
        data = self._to_table_json()
        tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.table.json')
        data = numpy_arrays_to_lists(data)
        util.json_dump_safer(data, codecs.open(tmp_path, 'w', encoding='utf-8'))
        self._set_file(tmp_path, is_tmp=True, extension='.table.json')
        super(Table, self).bind_to_run(*args, **kwargs)

    @classmethod
    def get_media_subdir(cls):
        return os.path.join('media', 'table')

    def to_json(self, run):
        json_dict = super(Table, self).to_json(run)
        json_dict['_type'] = 'table-file'
        json_dict['ncols'] = len(self.columns)
        json_dict['nrows'] = len(self.data)
        return json_dict


class Audio(BatchableMedia):
    """
        Wandb class for audio clips.

        Args:
            data_or_path (string or numpy array): A path to an audio file
                or a numpy array of audio data.
            sample_rate (int): Sample rate, required when passing in raw
                numpy array of audio data.
            caption (string): Caption to display with audio.
    """

    def __init__(self, data_or_path, sample_rate=None, caption=None):
        """Accepts a path to an audio file or a numpy array of audio data.
        """
        super(Audio, self).__init__()
        self._duration = None
        self._sample_rate = sample_rate
        self._caption = caption

        if isinstance(data_or_path, six.string_types):
            self._set_file(data_or_path, is_tmp=False)
        else:
            if sample_rate == None:
                raise ValueError('Argument "sample_rate" is required when instantiating wandb.Audio with raw data.')

            soundfile = util.get_module(
                "soundfile", required='Raw audio requires the soundfile package. To get it, run "pip install soundfile"')

            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.wav')
            soundfile.write(tmp_path, data_or_path, sample_rate)
            self._duration = len(data_or_path) / float(sample_rate)

            self._set_file(tmp_path, is_tmp=True)

    @classmethod
    def get_media_subdir(cls):
        return os.path.join('media', 'audio')

    def to_json(self, run):
        json_dict = super(Audio, self).to_json(run)
        json_dict.update({
            '_type': 'audio-file',
            'sample_rate': self._sample_rate,
            'caption': self._caption,
        })
        return json_dict

    @classmethod
    def seq_to_json(cls, seq, run, key, step):
        audio_list = list(seq)
        for audio in audio_list:
            if not audio.is_bound():
                audio.bind_to_run(run, key, step)

        sf = util.get_module(
            "soundfile", required="wandb.Audio requires the soundfile package. To get it, run: pip install soundfile")
        base_path = os.path.join(run.dir, "media", "audio")
        util.mkdir_exists_ok(base_path)
        meta = {
            "_type": "audio",
            "count": len(audio_list),
            'audio': [a.to_json(run) for a in audio_list],
        }
        sample_rates = cls.sample_rates(audio_list)
        if sample_rates:
            meta["sampleRates"] = sample_rates
        durations = cls.durations(audio_list)
        if durations:
            meta["durations"] = durations
        captions = cls.captions(audio_list)
        if captions:
            meta["captions"] = captions

        return meta

    @classmethod
    def durations(cls, audio_list):
        return [a._duration for a in audio_list]

    @classmethod
    def sample_rates(cls, audio_list):
        return [a._sample_rate for a in audio_list]

    @classmethod
    def captions(cls, audio_list):
        captions = [a._caption for a in audio_list]
        if all(c is None for c in captions):
            return False
        else:
            return ['' if c == None else c for c in captions]


def is_numpy_array(data):
    np = util.get_module(
        "numpy", required="Logging raw point cloud data requires numpy")
    return isinstance(data, np.ndarray)


class Object3D(BatchableMedia):
    """
        Wandb class for 3D point clouds.

        Args:
            data_or_path (numpy array | string | io ):
                Object3D can be initialized from a file or a numpy array.

                The file types supported are obj, gltf, babylon, stl.  You can pass a path to
                    a file or an io object and a file_type which must be one of `'obj', 'gltf', 'babylon', 'stl'`.

                The shape of the numpy array must be one of either:
                ```
                [[x y z],       ...] nx3
                [x y z c],     ...] nx4 where c is a category with supported range [1, 14]
                [x y z r g b], ...] nx4 where is rgb is color
                ```

    """

    SUPPORTED_TYPES = set(['obj', 'gltf', 'babylon', 'stl'])

    def __init__(self, data_or_path, **kwargs):
        super(Object3D, self).__init__()

        if hasattr(data_or_path, 'name'):
            # if the file has a path, we just detect the type and copy it from there
            data_or_path = data_or_path.name

        if hasattr(data_or_path, 'read'):
            if hasattr(data_or_path, 'seek'):
                data_or_path.seek(0)
            object3D = data_or_path.read()

            extension = kwargs.pop("file_type", None)
            if extension == None:
                raise ValueError(
                    "Must pass file type keyword argument when using io objects.")
            if extension not in Object3D.SUPPORTED_TYPES:
                raise ValueError("Object 3D only supports numpy arrays or files of the type: " +
                                 ", ".join(Object3D.SUPPORTED_TYPES))

            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.' + extension)
            with open(tmp_path, "w") as f:
                f.write(object3D)

            self._set_file(tmp_path, is_tmp=True)
        elif isinstance(data_or_path, six.string_types):
            path = data_or_path
            try:
                extension = os.path.splitext(data_or_path)[1][1:]
            except:
                raise ValueError(
                    "File type must have an extension")
            if extension not in Object3D.SUPPORTED_TYPES:
                raise ValueError("Object 3D only supports numpy arrays or files of the type: " +
                                 ", ".join(Object3D.SUPPORTED_TYPES))

            self._set_file(data_or_path, is_tmp=False)
        # Supported different types and scene for 3D scenes
        elif 'type' in data_or_path:
            if data_or_path['type'] == 'lidar/beta':
                data = {
                    'type': data_or_path['type'],
                    'points': data_or_path['points'].tolist(),
                    'boxes': data_or_path['boxes'].tolist(),
                }
            else:
                raise ValueError("Type not supported, only 'lidar/beta' is currently supported")

            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.pts.json')
            json.dump(data, codecs.open(tmp_path, 'w', encoding='utf-8'),
                      separators=(',', ':'), sort_keys=True, indent=4)
            self._set_file(tmp_path, is_tmp=True, extension='.pts.json')
        elif is_numpy_array(data_or_path):
            data = data_or_path

            if len(data.shape) != 2 or data.shape[1] not in {3, 4, 6}:
                raise ValueError("""The shape of the numpy array must be one of either
                                    [[x y z],       ...] nx3
                                     [x y z c],     ...] nx4 where c is a category with supported range [1, 14]
                                     [x y z r g b], ...] nx4 where is rgb is color""")

            data = data.tolist()
            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.pts.json')
            json.dump(data, codecs.open(tmp_path, 'w', encoding='utf-8'),
                      separators=(',', ':'), sort_keys=True, indent=4)
            self._set_file(tmp_path, is_tmp=True, extension='.pts.json')
        else:
            raise ValueError("data must be a numpy or a file object")

    @classmethod
    def get_media_subdir(self):
        return os.path.join('media', 'object3D')

    def to_json(self, run):
        json_dict = super(Object3D, self).to_json(run)
        json_dict['_type'] = 'object3D-file'
        return json_dict

    @classmethod
    def seq_to_json(cls, threeD_list, run, key, step):
        threeD_list = list(threeD_list)
        for i, obj in enumerate(threeD_list):
            if not obj.is_bound():
                obj.bind_to_run(run, key, step, id_=i)

        jsons = [obj.to_json(run) for obj in threeD_list]

        for obj in jsons:
            if not obj['path'].startswith(cls.get_media_subdir()):
                raise ValueError('Files in an array of Object3D\'s must be in the {} directory, not {}'.format(
                    cls.get_media_subdir(), obj['path']))

        return {
            "_type": "object3D",
            "filenames": [os.path.relpath(j['path'], cls.get_media_subdir()) for j in jsons],
            "count": len(jsons),
            'objects': jsons,
        }


class Molecule(BatchableMedia):
    """
        Wandb class for Molecular data

        Args:
            data_or_path ( string | io ):
                Molecule can be initialized from a file name or an io object.
    """

    SUPPORTED_TYPES = set(['pdb', 'pqr', 'mmcif', 'mcif', 'cif', 'sdf', 'sd', 'gro', 'mol2', 'mmtf'])

    def __init__(self, data_or_path, **kwargs):
        super(Molecule, self).__init__(**kwargs)

        if hasattr(data_or_path, 'name'):
            # if the file has a path, we just detect the type and copy it from there
            data_or_path = data_or_path.name

        if hasattr(data_or_path, 'read'):
            if hasattr(data_or_path, 'seek'):
                data_or_path.seek(0)
            molecule = data_or_path.read()

            extension = kwargs.pop("file_type", None)
            if extension == None:
                raise ValueError(
                    "Must pass file type keyword argument when using io objects.")
            if extension not in Molecule.SUPPORTED_TYPES:
                raise ValueError("Molecule 3D only supports files of the type: " +
                                 ", ".join(Molecule.SUPPORTED_TYPES))

            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.' + extension)
            with open(tmp_path, "w") as f:
                f.write(molecule)

            self._set_file(tmp_path, is_tmp=True)
        elif isinstance(data_or_path, six.string_types):
            path = data_or_path
            try:
                extension = os.path.splitext(data_or_path)[1][1:]
            except:
                raise ValueError(
                    "File type must have an extension")
            if extension not in Molecule.SUPPORTED_TYPES:
                raise ValueError("Molecule only supports files of the type: " +
                                 ", ".join(Molecule.SUPPORTED_TYPES))

            self._set_file(data_or_path, is_tmp=False)
        else:
            raise ValueError("Data must be file name or a file object")

    @classmethod
    def get_media_subdir(self):
        return os.path.join('media', 'molecule')

    def to_json(self, run):
        json_dict = super(Molecule, self).to_json(run)
        json_dict['_type'] = 'molecule-file'
        if self._caption:
            json_dict['caption'] = self._caption
        return json_dict

    @classmethod
    def seq_to_json(cls, molecule_list, run, key, step):
        molecule_list = list(molecule_list)
        for i, obj in enumerate(molecule_list):
            if not obj.is_bound():
                obj.bind_to_run(run, key, step, id_=i)

        jsons = [obj.to_json(run) for obj in molecule_list]

        for obj in jsons:
            if not obj['path'].startswith(cls.get_media_subdir()):
                raise ValueError('Files in an array of Molecule\'s must be in the {} directory, not {}'.format(
                    cls.get_media_subdir(), obj['path']))

        return {
            "_type": "molecule",
            "filenames": [obj['path'] for obj in jsons],
            "count": len(jsons),
            "captions": Media.captions(molecule_list)
        }


class Html(BatchableMedia):
    """
        Wandb class for arbitrary html

        Arguments:
            data (string or io object): HTML to display in wandb
            inject (boolean): Add a stylesheet to the HTML object.  If set
                to False the HTML will pass through unchanged.
    """

    def __init__(self, data, inject=True):
        super(Html, self).__init__()

        if isinstance(data, str):
            self.html = data
        elif hasattr(data, 'read'):
            if hasattr(data, 'seek'):
                data.seek(0)
            self.html = data.read()
        else:
            raise ValueError("data must be a string or an io object")
        if inject:
            self.inject_head()

        tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.html')
        with open(tmp_path, 'w') as out:
            print(self.html, file=out)

        self._set_file(tmp_path, is_tmp=True)

    def inject_head(self):
        join = ""
        if "<head>" in self.html:
            parts = self.html.split("<head>", 1)
            parts[0] = parts[0] + "<head>"
        elif "<html>" in self.html:
            parts = self.html.split("<html>", 1)
            parts[0] = parts[0] + "<html><head>"
            parts[1] = "</head>" + parts[1]
        else:
            parts = ["", self.html]
        parts.insert(
            1, '<base target="_blank"><link rel="stylesheet" type="text/css" href="https://app.wandb.ai/normalize.css" />')
        self.html = join.join(parts).strip()

    @classmethod
    def get_media_subdir(self):
        return os.path.join('media', 'html')

    def to_json(self, run):
        json_dict = super(Html, self).to_json(run)
        json_dict['_type'] = 'html-file'
        return json_dict

    @classmethod
    def seq_to_json(cls, html_list, run, key, step):
        base_path = os.path.join(run.dir, cls.get_media_subdir())
        util.mkdir_exists_ok(base_path)
        for i, h in enumerate(html_list):
            if not h.is_bound():
                h.bind_to_run(run, key, step, id_=i)
        meta = {
            "_type": "html",
            "count": len(html_list),
            'html': [h.to_json(run) for h in html_list]
        }
        return meta


class Video(BatchableMedia):

    """
        Wandb representation of video.

        Args:
            data_or_path (numpy array | string | io):
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
            filename = os.path.join(MEDIA_TMP.name, util.generate_id() + '.'+ self._format)
            with open(filename, "wb") as f:
                f.write(data_or_path.read())
            self._set_file(filename, is_tmp=True)
        elif isinstance(data_or_path, six.string_types):
            _, ext = os.path.splitext(data_or_path)
            ext = ext[1:].lower()
            if ext not in Video.EXTS:
                raise ValueError("wandb.Video accepts %s formats" % ", ".join(Video.EXTS))
            self._set_file(data_or_path, is_tmp=False)
            #ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 data_or_path
        else:
            if hasattr(data_or_path, "numpy"):  # TF data eager tensors
                self.data = data_or_path.numpy()
            elif is_numpy_array(data_or_path):
                self.data = data_or_path
            else:
                raise ValueError("wandb.Video accepts a file path or numpy like data as input")
            self.encode()

    def encode(self):
        mpy = util.get_module(
            "moviepy.editor", required='wandb.Video requires moviepy and imageio when passing raw data.  Install with "pip install moviepy imageio"')
        tensor = self._prepare_video(self.data)
        _, self._height, self._width, self._channels = tensor.shape

        # encode sequence of images into gif string
        clip = mpy.ImageSequenceClip(list(tensor), fps=self._fps)

        filename = os.path.join(MEDIA_TMP.name, util.generate_id() + '.'+ self._format)
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
        return os.path.join('media', 'videos')

    def to_json(self, run):
        json_dict = super(Video, self).to_json(run)
        json_dict['_type'] = 'video-file'

        if self._width is not None:
            json_dict['width'] = self._width
        if self._height is not None:
            json_dict['height'] = self._height
        if self._caption:
            json_dict['caption'] = self._caption

        return json_dict

    def _prepare_video(self, V):
        """This logic was mostly taken from tensorboardX"""
        np = util.get_module(
            "numpy", required='wandb.Video requires numpy when passing raw data. To get it, run "pip install numpy".')
        if V.ndim < 4:
            raise ValueError("Video must be atleast 4 dimensions: time, channels, height, width")
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
            len_addition = int(2**V.shape[0].bit_length() - V.shape[0])
            V = np.concatenate(
                (V, np.zeros(shape=(len_addition, t, c, h, w))), axis=0)

        n_rows = 2**((b.bit_length() - 1) // 2)
        n_cols = V.shape[0] // n_rows

        V = np.reshape(V, newshape=(n_rows, n_cols, t, c, h, w))
        V = np.transpose(V, axes=(2, 0, 4, 1, 5, 3))
        V = np.reshape(V, newshape=(t, n_rows * h, n_cols * w, c))
        return V

    @classmethod
    def seq_to_json(cls, videos, run, key, step):
        base_path = os.path.join(run.dir, cls.get_media_subdir())
        util.mkdir_exists_ok(base_path)
        for i, v in enumerate(videos):
            if not v.is_bound():
                v.bind_to_run(run, key, step, id_=i)
        meta = {
            "_type": "videos",
            "count": len(videos),
            'videos': [v.to_json(run) for v in videos],
            "captions": Video.captions(videos)
        }
        return meta

    @classmethod
    def captions(cls, videos):
        if videos[0]._caption != None:
            return [v._caption for v in videos]
        else:
            return False


class Image(BatchableMedia):
    """
        Wandb class for images.

        Args:
            data_or_path (numpy array | string | io): Accepts numpy array of
                image data, or a PIL image. The class attempts to infer
                the data format and converts it.
            mode (string): The PIL mode for an image. Most common are "L", "RGB",
                "RGBA". Full explanation at https://pillow.readthedocs.io/en/4.2.x/handbook/concepts.html#concept-modes.
            caption (string): Label for display of image.
    """

    MAX_THUMBNAILS = 108

    # PIL limit
    MAX_DIMENSION = 65500

    def __init__(self, data_or_path, mode=None, caption=None, grouping=None, boxes=None, masks=None):
        super(Image, self).__init__()
        # TODO: We should remove grouping, it's a terrible name and I don't
        # think anyone uses it.

        self._grouping = grouping
        self._caption = caption
        self._width = None
        self._height = None
        self._image = None
        
        self._boxes = None 
        if boxes: 
            if not isinstance(boxes, dict):
                raise ValueError("Images \"boxes\" argument must be a dictionary")
            boxes_final = {}
            for key in boxes:
                boxes_final[key] = BoundingBoxes2D(boxes[key], key)
            self._boxes = boxes_final

        self._masks = None
        if masks:
            if not isinstance(masks, dict):
                raise ValueError("Images \"masks\" argument must be a dictionary")
            masks_final = {}
            for key in masks:
                masks_final[key] = ImageMask(masks[key], key)
            self._masks = masks_final

        if isinstance(data_or_path, six.string_types):
            self._set_file(data_or_path, is_tmp=False)
        else:
            data = data_or_path

            PILImage = util.get_module(
                "PIL.Image", required='wandb.Image needs the PIL package. To get it, run "pip install pillow".')
            if util.is_matplotlib_typename(util.get_full_typename(data)):
                buf = six.BytesIO()
                util.ensure_matplotlib_figure(data).savefig(buf)
                self._image = PILImage.open(buf)
            elif isinstance(data, PILImage.Image):
                self._image = data
            elif util.is_pytorch_tensor_typename(util.get_full_typename(data)):
                vis_util = util.get_module(
                    "torchvision.utils", "torchvision is required to render images")
                if hasattr(data, "requires_grad") and data.requires_grad:
                    data = data.detach()
                data = vis_util.make_grid(data, normalize=True)
                self._image = PILImage.fromarray(data.mul(255).clamp(
                    0, 255).byte().permute(1, 2, 0).cpu().numpy())
            else:
                if hasattr(data, "numpy"):  # TF data eager tensors
                    data = data.numpy()
                if data.ndim > 2:
                    data = data.squeeze()  # get rid of trivial dimensions as a convenience
                self._image = PILImage.fromarray(
                    self.to_uint8(data), mode=mode or self.guess_mode(data))

            self._width, self._height = self._image.size

            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.png')
            self._image.save(tmp_path, transparency=None)
            self._set_file(tmp_path, is_tmp=True)

    @classmethod
    def get_media_subdir(cls):
        return os.path.join('media', 'images')

    def bind_to_run(self, *args, **kwargs):
        super(Image, self).bind_to_run(*args, **kwargs)
        if self._boxes is not None:
            for k in self._boxes:
                self._boxes[k].bind_to_run(*args, **kwargs)

        if self._masks is not None:
            for k in self._masks:
                self._masks[k].bind_to_run(*args, **kwargs)

    def to_json(self, run):
        json_dict = super(Image, self).to_json(run)
        json_dict['_type'] = 'image-file'
        json_dict['format'] = "png"

        if self._width is not None:
            json_dict['width'] = self._width
        if self._height is not None:
            json_dict['height'] = self._height
        if self._grouping:
            json_dict['grouping'] = self._grouping
        if self._caption:
            json_dict['caption'] = self._caption
        if self._boxes:
            json_dict['boxes'] = {
                    k: box.to_json(run) for (k, box) in self._boxes.items()}
        if self._masks:
            json_dict['masks'] = {
                k: mask.to_json(run) for (k, mask) in self._masks.items()}

        return json_dict

    def guess_mode(self, data):
        """
        Guess what type of image the np.array is representing
        """
        # TODO: do we want to support dimensions being at the beginning of the array?
        if data.ndim == 2:
            return "L"
        elif data.shape[-1] == 3:
            return "RGB"
        elif data.shape[-1] == 4:
            return "RGBA"
        else:
            raise ValueError(
                "Un-supported shape for image conversion %s" % list(data.shape))

    @classmethod
    def to_uint8(self, data):
        """
        Converts floating point image on the range [0,1] and integer images
        on the range [0,255] to uint8, clipping if necessary.
        """
        np = util.get_module(
            "numpy", required="wandb.Image requires numpy if not supplying PIL Images: pip install numpy")

        # I think it's better to check the image range vs the data type, since many
        # image libraries will return floats between 0 and 255

        # some images have range -1...1 or 0-1
        dmin = np.min(data)
        if dmin < 0:
            data = (data - np.min(data)) / np.ptp(data)
        if np.max(data) <= 1.0:
            data = (data * 255).astype(np.int32)

        #assert issubclass(data.dtype.type, np.integer), 'Illegal image format.'
        return data.clip(0, 255).astype(np.uint8)

    @classmethod
    def seq_to_json(cls, images, run, key, step):
        """
        Combines a list of images into a single sprite returning meta information
        """
        from PIL import Image as PILImage
        base = os.path.join(run.dir, cls.get_media_subdir())
        width, height = images[0]._image.size
        num_images_to_log = len(images)

        if num_images_to_log > Image.MAX_THUMBNAILS:
            logging.warning(
                "Only %i images will be uploaded." % Image.MAX_THUMBNAILS)
            num_images_to_log = Image.MAX_THUMBNAILS
            images = images[:num_images_to_log]

        if width * num_images_to_log > Image.MAX_DIMENSION:
            max_images_by_dimension = Image.MAX_DIMENSION // width
            logging.warning('Only {} images will be uploaded. The maximum total width for a set of thumbnails is 65,500px, or {} images, each with a width of {} pixels.'.format(
                max_images_by_dimension, max_images_by_dimension, width))
            num_images_to_log = max_images_by_dimension

        total_width = width * num_images_to_log
        sprite = PILImage.new(
            mode='RGB',
            size=(total_width, height),
            color=(0, 0, 0))
        for i, image in enumerate(images[:num_images_to_log]):
            location = width * i
            sprite.paste(image._image, (location, 0))
        fname = '{}_{}.png'.format(key, step)
        # fname may contain a slash so we create the directory
        util.mkdir_exists_ok(os.path.dirname(os.path.join(base, fname)))
        sprite.save(os.path.join(base, fname), transparency=None)
        meta = {"width": width, "height": height, "format": "png",
                "count": num_images_to_log, "_type": "images"}
        # TODO: hacky way to enable image grouping for now
        grouping = images[0]._grouping
        if grouping:
            meta["grouping"] = grouping

        captions = Image.all_captions(images)

        if captions:
            meta["captions"] = captions

        all_masks = Image.all_masks(images, run, key, step)

        if all_masks:
            meta["all_masks"] = all_masks

        all_boxes = Image.all_boxes(images, run, key, step)

        if all_boxes:
            meta["all_boxes"] = all_boxes

        return meta

    @classmethod
    def all_masks(cls, images, run, run_key, step):
        all_mask_groups = []
        for image in images:
            if image._masks:
                mask_group = {}
                for k in image._masks:
                    mask = image._masks[k]
                    mask.bind_to_run(run, run_key, step)
                    mask_group[k] = mask.to_json(run)
                all_mask_groups.append(mask_group)
            else:
                all_mask_groups.append(None)
        if all_mask_groups and not all(x is None for x in all_mask_groups):
            return all_mask_groups
        else:
            return False

    @classmethod
    def all_boxes(cls, images, run, run_key, step):
        all_box_groups = []
        for image in images:
            if image._boxes:
                box_group = {}
                for k in image._boxes:
                    box = image._boxes[k]
                    box.bind_to_run(run, run_key, step)
                    box_group[k] = box.to_json(run)
                all_box_groups.append(box_group)
            else:
                all_box_groups.append(None)
        if all_box_groups and not all(x is None for x in all_box_groups):
            return all_box_groups
        else: 
            return False

    @classmethod
    def all_captions(cls, images ):
        if images[0]._caption != None:
            return [i._caption for i in images]
        else:
            return False

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
        util.json_dump_uncompressed(self._val, codecs.open(tmp_path, 'w', encoding='utf-8'))
        self._set_file(tmp_path, is_tmp=True, extension=ext)

    def get_media_subdir(self):
        return os.path.join('media', 'metadata', self.type_name())

    def to_json(self, run):
        json_dict = super(JSONMetadata, self).to_json(run)
        json_dict['_type'] = self.type_name()

        return json_dict

    # These methods should be overridden in the child class
    def type_name(self):
        return "metadata"

    def validate(self, val):
        return True


class BoundingBoxes2D(JSONMetadata):
    """
    Wandb class for 2D bounding Boxes
    """

    def __init__(self, val, key, **kwargs):
        super(BoundingBoxes2D, self).__init__(val)
        self._val = val["box_data"]
        self._key = key
        # Add default class mapping
        if not "class_labels" in val:
            np = util.get_module("numpy", required="Semantic Segmentation mask support requires numpy")
            classes = np.unique(list(map( lambda box: box["class_id"], val["box_data"]))).astype(np.int32).tolist()
            class_labels = dict((c, "class_" + str(c)) for c in classes)
            self._class_labels = class_labels
        else:
            self._class_labels = val["class_labels"]

    def bind_to_run(self, run, key, step):
        # bind_to_run key argument is the Image parent key
        # the self._key value is the mask's sub key
        super(BoundingBoxes2D, self).bind_to_run(run, key, step)
        run._add_singleton("bounding_box/class_labels", key + "_wandb_delimeter_" + self._key , self._class_labels)


    def type_name(self):
        return "boxes2D"

    def validate(self, val):
        # Optional argument
        if ("class_labels" in val):
            for k, v in list(val["class_labels"].items()):
                if (not isinstance(k, numbers.Number)) or (not isinstance(v, six.string_types)):
                    raise TypeError("Class labels must be a dictionary of numbers to string")

        boxes = val['box_data']
        if not isinstance(boxes, collections.Sequence):
            raise TypeError("Boxes must be a list")

        for box in boxes:
            # Required arguments
            error_str = "Each box must contain a position with: middle, width, and height or \
                    \nminX, maxX, minY, maxY."
            if not "position" in box:
                raise TypeError(error_str)
            else:
                valid = False
                if "middle" in box["position"] and len(box["position"]["middle"]) == 2 and \
                   has_num(box["position"], "width") and \
                   has_num(box["position"], "height"):
                    valid = True
                elif has_num(box["position"], "minX") and \
                        has_num(box["position"], "maxX") and \
                        has_num(box["position"], "minY") and \
                        has_num(box["position"], "maxY"):
                    valid = True

                if not valid:
                    raise TypeError(error_str)

            # Optional arguments
            if ("scores" in box) and not isinstance(box["scores"], dict):
                raise TypeError("Box scores must be a dictionary")
            elif ("scores" in box):
                for k, v in list(box["scores"].items()):
                    if not isinstance(k, six.string_types):
                        raise TypeError("A score key must be a string")
                    if not isinstance(v, numbers.Number):
                        raise TypeError("A score value must be a number")

            if ("class_id" in box) and not isinstance(box["class_id"], six.integer_types):
                raise TypeError("A box's class_id must be an integer")

            # Optional
            if ("box_caption" in box) and not isinstance(box["box_caption"], six.string_types):
                raise TypeError("A box's caption must be a string")


class ImageMask(Media):
    """
    Wandb class for image masks, useful for segmentation tasks
    """

    def __init__(self, val, key, **kwargs):
        super(ImageMask, self).__init__()

        # Add default class mapping
        if not "class_labels" in val:
            np = util.get_module("numpy", required="Semantic Segmentation mask support requires numpy")
            classes = np.unique(val["mask_data"]).astype(np.int32).tolist()
            class_labels = dict((c, "class_" + str(c)) for c in classes)
            val["class_labels"] = class_labels

        self.validate(val)
        self._val = val
        self._key = key

        ext = "." + self.type_name() + ".png"
        tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + ext)

        PILImage = util.get_module(
            "PIL.Image", required='wandb.Image needs the PIL package. To get it, run "pip install pillow".')
        image = PILImage.fromarray(val["mask_data"], mode="L")

        image.save(tmp_path, transparency=None)
        self._set_file(tmp_path, is_tmp=True, extension=ext)

    def bind_to_run(self, run, key, step):
        # bind_to_run key argument is the Image parent key
        # the self._key value is the mask's sub key
        super(ImageMask, self).bind_to_run(run, key, step)
        class_labels = self._val["class_labels"]

        run._add_singleton("mask/class_labels", key + "_wandb_delimeter_" + self._key , class_labels)

    def get_media_subdir(self):
        return os.path.join('media', 'images', self.type_name())

    def to_json(self, run):
        json_dict = super(ImageMask, self).to_json(run)
        json_dict['_type'] = self.type_name()

        return json_dict

    def type_name(self):
        return "mask"

    def validate(self, mask):
        # 2D Make this work with all tensor(like) types
        if not "mask_data" in mask:
            raise TypeError("Missing key \"mask_data\": A mask requires mask data(A 2D array representing the predctions)")
        else:
            error_str = "mask_data must be a 2d array"
            shape = mask["mask_data"].shape
            if len(shape) != 2:
                raise TypeError(error_str)
            if not ((mask["mask_data"] >= 0).all() and (mask["mask_data"] <= 255).all()) and \
                    mask["mask_data"].dtype('int8').kind == "i":
                raise TypeError("Mask data must be integers between 0 and 255")

        # Optional argument
        if ("class_labels" in mask):
            for k, v in list(mask["class_labels"].items()):
                if (not isinstance(k, numbers.Number)) or (not isinstance(v, six.string_types)):
                    raise TypeError("Class labels must be a dictionary of numbers to string")


class Plotly(Media):
    """
        Wandb class for plotly plots.

        Args:
            val: matplotlib or plotly figure
    """

    @classmethod
    def make_plot_media(cls, val):
        if util.is_matplotlib_typename(util.get_full_typename(val)):
            val = util.ensure_matplotlib_figure(val)
            if any(len(ax.images) > 0 for ax in val.axes):
                return Image(val)
            val = util.ensure_matplotlib_figure(val)
            # otherwise, convert to plotly figure
            tools = util.get_module(
                "plotly.tools", required="plotly is required to log interactive plots, install with: pip install plotly or convert the plot to an image with `wandb.Image(plt)`")
            val = tools.mpl_to_plotly(val)
        return cls(val)

    def __init__(self, val, **kwargs):
        super(Plotly, self).__init__()
        if not util.is_plotly_figure_typename(util.get_full_typename(val)):
            raise ValueError(
                'Logged plots must be plotly figures, or matplotlib plots convertible to plotly via mpl_to_plotly')

        tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.plotly.json')
        val = numpy_arrays_to_lists(val.to_plotly_json())
        util.json_dump_safer(val, codecs.open(tmp_path, 'w', encoding='utf-8'))
        self._set_file(tmp_path, is_tmp=True, extension='.plotly.json')

    def get_media_subdir(self):
        return os.path.join('media', 'plotly')

    def to_json(self, run):
        json_dict = super(Plotly, self).to_json(run)
        json_dict['_type'] = 'plotly-file'
        return json_dict


class Graph(Media):
    """Wandb class for graphs

    This class is typically used for saving and diplaying neural net models.  It
    represents the graph as an array of nodes and edges.  The nodes can have
    labels that can be visualized by wandb.

    Examples:
        Import a keras model:
        ```
            Graph.from_keras(keras_model)
        ```

    Attributes:
        format (string): Format to help wandb display the graph nicely.
        nodes ([wandb.Node]): List of wandb.Nodes
        nodes_by_id (dict): dict of ids -> nodes
        edges ([(wandb.Node, wandb.Node)]): List of pairs of nodes interpreted as edges
        loaded (boolean): Flag to tell whether the graph is completely loaded
        root (wandb.Node): root node of the graph
    """

    def __init__(self, format="keras"):
        super(Graph, self).__init__()
        # LB: TODO: I think we should factor criterion and criterion_passed out
        self.format = format
        self.nodes = []
        self.nodes_by_id = {}
        self.edges = []
        self.loaded = False
        self.criterion = None
        self.criterion_passed = False
        self.root = None  # optional root Node if applicable

    def _to_graph_json(self, run=None):
        # Needs to be it's own function for tests
        return {"format": self.format,
                "nodes": [node.to_json() for node in self.nodes],
                "edges": [edge.to_json() for edge in self.edges]}

    def bind_to_run(self, *args, **kwargs):
        data = self._to_graph_json()
        tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.graph.json')
        data = numpy_arrays_to_lists(data)
        util.json_dump_safer(data, codecs.open(tmp_path, 'w', encoding='utf-8'))
        self._set_file(tmp_path, is_tmp=True, extension='.graph.json')
        if self.is_bound():
            return
        super(Graph, self).bind_to_run(*args, **kwargs)

    @classmethod
    def get_media_subdir(cls):
        return os.path.join('media', 'graph')

    def to_json(self, run):
        json_dict = super(Graph, self).to_json(run)
        json_dict['_type'] = 'graph-file'
        return json_dict

    def __getitem__(self, nid):
        return self.nodes_by_id[nid]

    def pprint(self):
        for edge in self.edges:
            pprint.pprint(edge.attributes)
        for node in self.nodes:
            pprint.pprint(node.attributes)

    def add_node(self, node=None, **node_kwargs):
        if node is None:
            node = Node(**node_kwargs)
        elif node_kwargs:
            raise ValueError('Only pass one of either node ({node}) or other keyword arguments ({node_kwargs})'.format(
                node=node, node_kwargs=node_kwargs))
        self.nodes.append(node)
        self.nodes_by_id[node.id] = node

        return node

    def add_edge(self, from_node, to_node):
        edge = Edge(from_node, to_node)
        self.edges.append(edge)

        return edge

    @classmethod
    def from_keras(cls, model):
        graph = cls()
        # Shamelessly copied from keras/keras/utils/layer_utils.py

        if model.__class__.__name__ == 'Sequential':
            sequential_like = True
        elif not hasattr(model, "_is_graph_network") or not model._is_graph_network:
            # We treat subclassed models as a simple sequence of layers,
            # for logging purposes.
            sequential_like = True
        else:
            sequential_like = True
            nodes_by_depth = model._nodes_by_depth.values()
            nodes = []
            for v in nodes_by_depth:
                # TensorFlow2 doesn't insure inbound is always a list
                inbound = v[0].inbound_layers
                if not hasattr(inbound, '__len__'):
                    inbound = [inbound]
                if (len(v) > 1) or (len(v) == 1 and len(inbound) > 1):
                    # if the model has multiple nodes
                    # or if the nodes have multiple inbound_layers
                    # the model is no longer sequential
                    sequential_like = False
                    break
                nodes += v
            if sequential_like:
                # search for shared layers
                for layer in model.layers:
                    flag = False
                    if hasattr(layer, "_inbound_nodes"):
                        for node in layer._inbound_nodes:
                            if node in nodes:
                                if flag:
                                    sequential_like = False
                                    break
                                else:
                                    flag = True
                    if not sequential_like:
                        break

        relevant_nodes = None
        if sequential_like:
            # header names for the different log elements
            to_display = ['Layer (type)', 'Output Shape', 'Param #']
        else:
            relevant_nodes = []
            for v in model._nodes_by_depth.values():
                relevant_nodes += v

        layers = model.layers
        for i in range(len(layers)):
            node = Node.from_keras(layers[i])
            if hasattr(layers[i], '_inbound_nodes'):
                for in_node in layers[i]._inbound_nodes:
                    if relevant_nodes and in_node not in relevant_nodes:
                        # node is not part of the current network
                        continue
                    for in_layer in nest(in_node.inbound_layers):
                        inbound_keras_node = Node.from_keras(in_layer)

                        if (inbound_keras_node.id not in graph.nodes_by_id):
                            graph.add_node(inbound_keras_node)
                        inbound_node = graph.nodes_by_id[inbound_keras_node.id]

                        graph.add_edge(inbound_node, node)
            graph.add_node(node)
        return graph


class Node(WBValue):
    """
    Node used in :obj:`Graph`
    """

    def __init__(self, id=None, name=None, class_name=None, size=None, parameters=None, output_shape=None, is_output=None, num_parameters=None, node=None):
        self._attributes = {'name': None}
        self.in_edges = {}  # indexed by source node id
        self.out_edges = {}  # indexed by dest node id
        # optional object (eg. PyTorch Parameter or Module) that this Node represents
        self.obj = None

        if node is not None:
            self._attributes.update(node._attributes)
            del self._attributes['id']
            self.obj = node.obj

        if id is not None:
            self.id = id
        if name is not None:
            self.name = name
        if class_name is not None:
            self.class_name = class_name
        if size is not None:
            self.size = size
        if parameters is not None:
            self.parameters = parameters
        if output_shape is not None:
            self.output_shape = output_shape
        if is_output is not None:
            self.is_output = is_output
        if num_parameters is not None:
            self.num_parameters = num_parameters

    def to_json(self, run=None):
        return self._attributes

    def __repr__(self):
        return repr(self._attributes)

    @property
    def id(self):
        """Must be unique in the graph"""
        return self._attributes.get('id')

    @id.setter
    def id(self, val):
        self._attributes['id'] = val
        return val

    @property
    def name(self):
        """Usually the type of layer or sublayer"""
        return self._attributes.get('name')

    @name.setter
    def name(self, val):
        self._attributes['name'] = val
        return val

    @property
    def class_name(self):
        """Usually the type of layer or sublayer"""
        return self._attributes.get('class_name')

    @class_name.setter
    def class_name(self, val):
        self._attributes['class_name'] = val
        return val

    @property
    def functions(self):
        return self._attributes.get('functions', [])

    @functions.setter
    def functions(self, val):
        self._attributes["functions"] = val
        return val

    @property
    def parameters(self):
        return self._attributes.get('parameters', [])

    @parameters.setter
    def parameters(self, val):
        self._attributes["parameters"] = val
        return val

    @property
    def size(self):
        return self._attributes.get('size')

    @size.setter
    def size(self, val):
        """Tensor size"""
        self._attributes['size'] = tuple(val)
        return val

    @property
    def output_shape(self):
        return self._attributes.get('output_shape')

    @output_shape.setter
    def output_shape(self, val):
        """Tensor output_shape"""
        self._attributes['output_shape'] = val
        return val

    @property
    def is_output(self):
        return self._attributes.get('is_output')

    @is_output.setter
    def is_output(self, val):
        """Tensor is_output"""
        self._attributes['is_output'] = val
        return val

    @property
    def num_parameters(self):
        return self._attributes.get('num_parameters')

    @num_parameters.setter
    def num_parameters(self, val):
        """Tensor num_parameters"""
        self._attributes['num_parameters'] = val
        return val

    @property
    def child_parameters(self):
        return self._attributes.get('child_parameters')

    @child_parameters.setter
    def child_parameters(self, val):
        """Tensor child_parameters"""
        self._attributes['child_parameters'] = val
        return val

    @property
    def is_constant(self):
        return self._attributes.get('is_constant')

    @is_constant.setter
    def is_constant(self, val):
        """Tensor is_constant"""
        self._attributes['is_constant'] = val
        return val

    @classmethod
    def from_keras(cls, layer):
        node = cls()

        try:
            output_shape = layer.output_shape
        except AttributeError:
            output_shape = ['multiple']

        node.id = layer.name
        node.name = layer.name
        node.class_name = layer.__class__.__name__
        node.output_shape = output_shape
        node.num_parameters = layer.count_params()

        return node


class Edge(WBValue):
    """
    Edge used in :obj:`Graph`
    """

    def __init__(self, from_node, to_node):
        self._attributes = {}
        self.from_node = from_node
        self.to_node = to_node

    def __repr__(self):
        temp_attr = dict(self._attributes)
        del temp_attr['from_node']
        del temp_attr['to_node']
        temp_attr['from_id'] = self.from_node.id
        temp_attr['to_id'] = self.to_node.id
        return str(temp_attr)

    def to_json(self, run=None):
        return [self.from_node.id, self.to_node.id]

    @property
    def name(self):
        """Optional, not necessarily unique"""
        return self._attributes.get('name')

    @name.setter
    def name(self, val):
        self._attributes['name'] = val
        return val

    @property
    def from_node(self):
        return self._attributes.get('from_node')

    @from_node.setter
    def from_node(self, val):
        self._attributes['from_node'] = val
        return val

    @property
    def to_node(self):
        return self._attributes.get('to_node')

    @to_node.setter
    def to_node(self, val):
        self._attributes['to_node'] = val
        return val


def nest(thing):
    # Use tensorflows nest function if available, otherwise just wrap object in an array"""

    tfutil = util.get_module('tensorflow.python.util')
    if tfutil:
        return tfutil.nest.flatten(thing)
    else:
        return [thing]


def history_dict_to_json(run, payload, step=None):
    # Converts a History row dict's elements so they're friendly for JSON serialization.

    if step is None:
        # We should be at the top level of the History row; assume this key is set.
        step = payload['_step']

    # We use list here because we were still seeing cases of RuntimeError dict changed size
    for key in list(payload):
        val = payload[key]
        if isinstance(val, dict):
            payload[key] = history_dict_to_json(run, val, step=step)
        else:
            payload[key] = val_to_json(run, key, val, step=step)

    return payload


def numpy_arrays_to_lists(payload):
    # Casts all numpy arrays to lists so we don't convert them to histograms, primarily for Plotly

    if isinstance(payload, dict):
        res = {}
        for key, val in six.iteritems(payload):
            res[key] = numpy_arrays_to_lists(val)
        return res
    elif isinstance(payload, collections.Sequence) and not isinstance(payload, six.string_types):
        return [numpy_arrays_to_lists(v) for v in payload]
    elif util.is_numpy_array(payload):
        return [numpy_arrays_to_lists(v) for v in payload.tolist()]

    return payload


def val_to_json(run, key, val, step='summary'):
    # Converts a wandb datatype to its JSON representation.

    converted = val
    typename = util.get_full_typename(val)

    if util.is_pandas_data_frame(val):
        assert step == 'summary', "We don't yet support DataFrames in History."
        return data_frame_to_json(val, run, key, step)
    elif util.is_matplotlib_typename(typename) or util.is_plotly_typename(typename):
        val = Plotly.make_plot_media(val)
    elif isinstance(val, collections.Sequence) and all(isinstance(v, WBValue) for v in val):
        # This check will break down if Image/Audio/... have child classes.
        if len(val) and isinstance(val[0], BatchableMedia) and all(isinstance(v, type(val[0])) for v in val):
            return val[0].seq_to_json(val, run, key, step)
        else:
            # TODO(adrian): Good idea to pass on the same key here? Maybe include
            # the array index?
            # There is a bug here: if this array contains two arrays of the same type of
            # anonymous media objects, their eventual names will collide.
            # This used to happen. The frontend doesn't handle heterogenous arrays
            #raise ValueError(
            #    "Mixed media types in the same list aren't supported")
            return [val_to_json(run, key, v, step=step) for v in val]

    if isinstance(val, WBValue):
        if isinstance(val, Media) and not val.is_bound():
            val.bind_to_run(run, key, step)
        return val.to_json(run)

    return converted


def data_frame_to_json(df, run, key, step):
    """!NODOC Encode a Pandas DataFrame into the JSON/backend format.

    Writes the data to a file and returns a dictionary that we use to represent
    it in `Summary`'s.

    Arguments:
        df (pandas.DataFrame): The DataFrame. Must not have columns named
            "wandb_run_id" or "wandb_data_frame_id". They will be added to the
            DataFrame here.
        run (wandb_run.Run): The Run the DataFrame is associated with. We need
            this because the information we store on the DataFrame is derived
            from the Run it's in.
        key (str): Name of the DataFrame, ie. the summary key path in which it's
            stored. This is for convenience, so people exploring the
            directory tree can have some idea of what is in the Parquet files.
        step: History step or "summary".

    Returns:
        A dict representing the DataFrame that we can store in summaries or
        histories. This is the format:
        {
            '_type': 'data-frame',
                # Magic field that indicates that this object is a data frame as
                # opposed to a normal dictionary or anything else.
            'id': 'asdf',
                # ID for the data frame that is unique to this Run.
            'format': 'parquet',
                # The file format in which the data frame is stored. Currently can
                # only be Parquet.
            'project': 'wfeas',
                # (Current) name of the project that this Run is in. It'd be
                # better to store the project's ID because we know it'll never
                # change but we don't have that here. We store this just in
                # case because we use the project name in identifiers on the
                # back end.
            'path': 'media/data_frames/sdlk.parquet',
                # Path to the Parquet file in the Run directory.
        }
    """
    pandas = util.get_module("pandas")
    fastparquet = util.get_module("fastparquet")
    missing_reqs = []
    if not pandas:
        missing_reqs.append('pandas')
    if not fastparquet:
        missing_reqs.append('fastparquet')
    if len(missing_reqs) > 0:
        raise wandb.Error("Failed to save data frame. Please run 'pip install %s'" % ' '.join(missing_reqs))

    data_frame_id = util.generate_id()

    df = df.copy()  # we don't want to modify the user's DataFrame instance.

    for col_name, series in df.items():
        for i, val in enumerate(series):
            if isinstance(val, WBValue):
                series.iat[i] = six.text_type(json.dumps(val_to_json(run, key, val, step)))

    # We have to call this wandb_run_id because that name is treated specially by
    # our filtering code
    df['wandb_run_id'] = pandas.Series(
        [six.text_type(run.id)] * len(df.index), index=df.index)

    df['wandb_data_frame_id'] = pandas.Series(
        [six.text_type(data_frame_id)] * len(df.index), index=df.index)
    frames_dir = os.path.join(run.dir, DATA_FRAMES_SUBDIR)
    util.mkdir_exists_ok(frames_dir)
    path = os.path.join(frames_dir, '{}-{}.parquet'.format(key, data_frame_id))
    fastparquet.write(path, df)

    return {
        'id': data_frame_id,
        '_type': 'data-frame',
        'format': 'parquet',
        'project': run.project_name(),  # we don't have the project ID here
        'entity': run.entity,
        'run': run.id,
        'path': path,
    }
