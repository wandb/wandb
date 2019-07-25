"""W&B rich data types like Image, Audio, etc. and JSON conversion functions.

A lot of functions take a "key" parameter. These are the dot-separated
Summary/History keys that we use on the front end.

Many also take a "step" parameter. These should be integer step numbers for
values saved in History and the string "summary" for values saved in Summary.

Values saved in History may incidentally also appear in Summary. In this case,
their "step" is still the History step number. Only if the value is put
directly into the Summary without being stored in History is its step set
to "summary".

The "to_json" functions in W&B are named loosely: they actually return Python
dict's or lists that are meant to be serialized to JSON. Some of them do even
more than this. They write something big to a file, then return a "JSON" blob
that refers to it across Runs.
"""

from __future__ import print_function

import hashlib
import itertools
import json
import pprint
import shutil
from six.moves import queue
import warnings

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
from wandb.compat import tempfile


# Get rid of cleanup warnings in Python 2.7.
warnings.filterwarnings('ignore', 'Implicitly cleaning up', RuntimeWarning, 'wandb.compat.tempfile')


# Staging directory so we can encode raw data into files, then hash them before
# we put them into the Run directory to be uploaded.
MEDIA_TMP = tempfile.TemporaryDirectory('wandb-media')


DATA_FRAMES_SUBDIR = os.path.join('media', 'data_frames')


def nest(thing):
    """Use tensorflows nest function if available, otherwise just wrap object in an array"""
    tfutil = util.get_module('tensorflow.python.util')
    if tfutil:
        return tfutil.nest.flatten(thing)
    else:
        return [thing]


def history_dict_to_json(run, payload, step=None):
    """Converts a History row dict's elements so they're friendly for JSON serialization.
    """
    if step is None:
        # We should be at the top level of the History row; assume this key is set.
        step = payload['_step']

    for key, val in six.iteritems(payload):
        if isinstance(val, dict):
            payload[key] = history_dict_to_json(run, val, step=step)
        else:
            payload[key] = val_to_json(run, key, val, step=step)

    return payload

def numpy_arrays_to_lists(payload):
    """Casts all numpy arrays to lists so we don't convert them to histograms, primarily for Plotly
    """
    for key,val in six.iteritems(payload):
        if isinstance(val, dict):
            payload[key] = numpy_arrays_to_lists(val)
        elif util.is_numpy_array(val):
            payload[key] = val.tolist()

    return payload


def val_to_json(run, key, val, step='summary'):
    """Converts a wandb datatype to its JSON representation.
    """
    converted = val
    typename = util.get_full_typename(val)

    if util.is_pandas_data_frame(val):
        assert step == 'summary', "We don't yet support DataFrames in History."
        return data_frame_to_json(val, run, key, step)
    elif util.is_matplotlib_typename(typename):
        # This handles plots with images in it because plotly doesn't support it
        # TODO: should we handle a list of plots?
        val = util.ensure_matplotlib_figure(val)
        if any(len(ax.images) > 0 for ax in val.axes):
            PILImage = util.get_module(
                "PIL.Image", required="Logging plots with images requires pil: pip install pillow")
            buf = six.BytesIO()
            val.savefig(buf)
            val = Image(PILImage.open(buf))
        else:
            converted = plot_to_json(val)
    elif util.is_plotly_typename(typename):
        converted = plot_to_json(val)
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


class WBValue(object):
    """Parent class for things that can be converted to JSON objects and
    stored in `run.summary`, `run.history` (`wandb.log()`), DataFrames,
    etc.

    The JSON objects will always have a _type attribute that indicates how
    to interpret the other fields.

    We picked the name "WBValue" to match what we call it on the front end.

    Arguments:
        run: A `wandb_run.Run` object in which this `WBValue` is going to
    be stored. This is a required parameter here to support referring to
    `Media` objects that are bound to other runs. In practice, many
    `WBValue` children may not need a Run to be passed to them because
    their JSON representations are self-contained.

    Returns:
        JSON-friendly `dict` representation of this object that can later be
    serialized to a string.
    """
    def to_json(self, run):
        """
        """
        raise NotImplementedError


def plot_to_json(obj):
    if util.is_matplotlib_typename(util.get_full_typename(obj)):
        tools = util.get_module(
            "plotly.tools", required="plotly is required to log interactive plots, install with: pip install plotly or convert the plot to an image with `wandb.Image(plt)`")
        obj = tools.mpl_to_plotly(obj)

    if util.is_plotly_typename(util.get_full_typename(obj)):
        return {"_type": "plotly", "plot": numpy_arrays_to_lists(obj.to_plotly_json())}
    else:
        return obj


def data_frame_to_json(df, run, key, step):
    """Encode a Pandas DataFrame into the JSON/backend format.

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
    if not pandas or not fastparquet:
        raise wandb.Error("Failed to save data frame: unable to import either pandas or fastparquet.")

    data_frame_id = util.generate_id()

    df = df.copy()  # we don't want to modify the user's DataFrame instance.

    for col_name, series in df.items():
        for i, val in enumerate(series):
            if isinstance(val, WBValue):
                series.iat[i] = six.text_type(json.dumps(val_to_json(run, key, val, step)))

    # We have to call this wandb_run_id because that name is treated specially by
    # our filtering code
    df['wandb_run_id'] = pandas.Series(
        [six.text_type(run.name)] * len(df.index), index=df.index)

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


class Graph(WBValue):
    def __init__(self, format="keras"):
        self.format = format
        self.nodes = []
        self.nodes_by_id = {}
        self.edges = []
        self.loaded = False
        self.criterion = None
        self.criterion_passed = False
        self.root = None  # optional root Node if applicable

    def to_json(self, run=None):
        return {"_type": "graph", "format": self.format,
                "nodes": [node.to_json() for node in self.nodes],
                "edges": [edge.to_json() for edge in self.edges]}

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


class Histogram(WBValue):
    MAX_LENGTH = 512

    def __init__(self, sequence=None, np_histogram=None, num_bins=64):
        """Accepts a sequence to be converted into a histogram or np_histogram can be set
        to a tuple of (values, bins_edges) as np.histogram returns i.e.

        wandb.log({"histogram": wandb.Histogram(
            np_histogram=np.histogram(data))})

        The maximum number of bins currently supported is 512
        """
        if np_histogram:
            if len(np_histogram) == 2:
                self.histogram = np_histogram[0]
                self.bins = np_histogram[1]
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


class Table(WBValue):
    MAX_ROWS = 300

    def __init__(self, columns=["Input", "Output", "Expected"], data=None, rows=None):
        """rows is kept for legacy reasons, we use data to mimic the Pandas api
        """
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

    def to_json(self, run=None):
        if len(self.data) > Table.MAX_ROWS:
            logging.warn(
                "The maximum number of rows to display per step is %i." % Table.MAX_ROWS)
        return {"_type": "table", "columns": self.columns, "data": self.data[:Table.MAX_ROWS]}


class Media(WBValue):
    """A WBValue that we store as a file outside JSON and show in a media panel
    on the front end.

    If necessary, we move or copy the file into the Run's media directory so that it gets
    uploaded.
    """

    def __init__(self, path, is_tmp=False, extension=None):
        self._path = path
        self._is_tmp = is_tmp
        self._extension = extension
        if extension is not None and not path.endswith(extension):
            raise ValueError('Media file extension "{}" must occur at the end of path "{}".'.format(extension, path))

        self._sha256 = hashlib.sha256(open(self._path, 'rb').read()).hexdigest()
        self._size = os.path.getsize(self._path)

        # The run under which this object is bound, if any.
        self._run = None

    @classmethod
    def get_media_subdir(cls):
        raise NotImplementedError

    def is_bound(self):
        return self._run is not None

    def bind_to_run(self, run, key, step, id_=None):
        """Bind this object to a particular Run.

        Calling this function is necessary so that we have somewhere specific to
        put the file associated with this object, from which other Runs can
        refer to it.
        """
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
            util.mkdir_exists_ok(base_path)

            if self._extension is None:
                rootname, extension = os.path.splitext(os.path.basename(self._path))
            else:
                extension = self._extension
                rootname = os.path.basename(self._path)[:-len(extension)]

            if self._is_tmp:
                if id_ is None:
                    id_ = self._sha256[:8]

                new_path = os.path.join(base_path, '{}_{}_{}{}'.format(key, step, id_, extension))

                shutil.move(self._path, new_path)

                self._path = new_path
                self._is_tmp = False
            else:
                new_path = os.path.join(base_path, '{}_{}{}'.format(rootname, self._sha256[:8], extension))
                shutil.copy(self._path, new_path)
                self._path = new_path

    def to_json(self, run):
        """Get the JSON-friendly dict that represents this object.

        Only works if `self.bind_to_run()` has previously been called.

        The resulting dict lets you load this object into other W&B runs.
        """
        if not self.is_bound():
            raise RuntimeError('Value of type {} must be bound to a run with bind_to_run() before being serialized to JSON.'.format(type(self).__name__))

        assert self._run is run, "For now we don't support referring to media files across runs."

        return {
            '_type': 'file',  # TODO(adrian): This isn't (yet) a real media type we support on the frontend.
            'path': os.path.relpath(self._path, self._run.dir),  # TODO(adrian): Convert this to a path with forward slashes.
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


class Audio(BatchableMedia):
    def __init__(self, data_or_path, sample_rate=None, caption=None):
        """Accepts a path to an audio file or a numpy array of audio data. 
        """
        self._duration = None
        self._sample_rate = sample_rate
        self._caption = caption

        if isinstance(data_or_path, six.string_types):
            super(Audio, self).__init__(data_or_path, is_tmp=False)
        else:
            if sample_rate == None:
                raise ValueError('Argument "sample_rate" is required when instantiating wandb.Audio with raw data.')

            soundfile = util.get_module(
                "soundfile", required='Raw audio requires the soundfile package. To get it, run "pip install soundfile"')

            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.wav')
            soundfile.write(tmp_path, data_or_path, sample_rate)
            self._duration = len(data_or_path) / float(sample_rate)

            super(Audio, self).__init__(tmp_path, is_tmp=True)

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
    SUPPORTED_TYPES = set(['obj', 'gltf', 'babylon', 'stl'])

    def __init__(self, data_or_path, **kwargs):
        """
        Accepts a path, a numpy array, or a 3D File of type: obj, gltf, babylon, stl.

        The shape of the numpy array must be one of either:
        [[x y z],       ...] nx3
         [x y z c],     ...] nx4 where c is a category with supported range [1, 14]
         [x y z r g b], ...] nx4 where is rgb is color"""
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

            super(Object3D, self).__init__(tmp_path, is_tmp=True)
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

            super(Object3D, self).__init__(data_or_path, is_tmp=False)
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
            super(Object3D, self).__init__(tmp_path, is_tmp=True, extension='.pts.json')
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
                raise ValueError('Files in an array of Object3D\'s must be in the {} directory, not {}'.format(cls.get_media_subdir(), obj['path']))

        return {
            "_type": "object3D",
            "filenames": [os.path.relpath(j['path'], cls.get_media_subdir()) for j in jsons],
            "count": len(jsons),
            'objects': jsons,
        }


class Html(BatchableMedia):
    def __init__(self, data, inject=True):
        """Accepts a string or file object containing valid html

        By default we inject a style reset into the doc to make it
        look resonable, passing inject=False will disable it.
        """
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

        super(Html, self).__init__(tmp_path, is_tmp=True)

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


class Image(BatchableMedia):
    MAX_THUMBNAILS = 100

    # PIL limit
    MAX_DIMENSION = 65500

    def __init__(self, data_or_path, mode=None, caption=None, grouping=None):
        """
        Accepts numpy array of image data, or a PIL image. The class attempts to infer
        the data format and converts it.

        If grouping is set to a number the interface combines N images.
        """

        self._grouping = grouping
        self._caption = caption
        self._width = None
        self._height = None
        self._image = None

        if isinstance(data_or_path, six.string_types):
            super(Image, self).__init__(data_or_path, is_tmp=False)
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
                if hasattr(data, "numpy"): # TF data eager tensors
                    data = data.numpy()
                data = data.squeeze()  # get rid of trivial dimensions as a convenience
                self._image = PILImage.fromarray(
                    self.to_uint8(data), mode=mode or self.guess_mode(data))

            self._width, self._height = self._image.size

            tmp_path = os.path.join(MEDIA_TMP.name, util.generate_id() + '.png')
            self._image.save(tmp_path)
            super(Image, self).__init__(tmp_path, is_tmp=True)

    @classmethod
    def get_media_subdir(cls):
        return os.path.join('media', 'images')

    def to_json(self, run):
        json_dict = super(Image, self).to_json(run)
        json_dict['_type'] = 'image-file'

        if self._width is not None:
            json_dict['width'] = self._width
        if self._height is not None:
            json_dict['height'] = self._height
        if self._grouping:
            json_dict['grouping'] = self._grouping
        if self._caption:
            json_dict['caption'] = self._caption

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

        if width * num_images_to_log > Image.MAX_DIMENSION:
            max_images_by_dimension = Image.MAX_DIMENSION // width
            logging.warning('Only {} images will be uploaded. The maximum total width for a set of thumbnails is 65,500px, or {} images, each with a width of {} pixels.'.format(max_images_by_dimension, max_images_by_dimension, width))
            num_images_to_log = max_images_by_dimension

        total_width = width * num_images_to_log
        sprite = PILImage.new(
            mode='RGB',
            size=(total_width, height),
            color=(0, 0, 0))
        for i, image in enumerate(images[:num_images_to_log]):
            location = width * i
            sprite.paste(image._image, (location, 0))
        fname = '{}_{}.jpg'.format(key, step)
        # fname may contain a slash so we create the directory
        util.mkdir_exists_ok(os.path.dirname(os.path.join(base, fname)))
        sprite.save(os.path.join(base, fname), transparency=0)
        meta = {"width": width, "height": height,
                "count": num_images_to_log, "_type": "images"}
        # TODO: hacky way to enable image grouping for now
        grouping = images[0]._grouping
        if grouping:
            meta["grouping"] = grouping
        captions = Image.captions(images[:num_images_to_log])
        if captions:
            meta["captions"] = captions
        return meta

    @classmethod
    def captions(cls, images):
        if images[0]._caption != None:
            return [i._caption for i in images]
        else:
            return False
