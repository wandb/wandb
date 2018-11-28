import itertools
import pprint
from six.moves import queue

import collections
import os
import logging
import six
import wandb
from wandb import util

def val_to_json(key, val, mode="summary", step=None):
    """Converts a wandb datatype to its JSON representation"""
    converted = val
    typename = util.get_full_typename(val)
    if util.is_matplotlib_typename(typename):
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
            converted = util.convert_plots(val)
    elif util.is_plotly_typename(typename):
        converted = util.convert_plots(val)
    if isinstance(val, Image) or isinstance(val, Audio):
        val = [val]

    if isinstance(val, collections.Sequence) and len(val) > 0:
        is_image = [isinstance(v, Image) for v in val]
        is_audio = [isinstance(v, Audio) for v in val]
        if all(is_image) or all(is_audio):
            cwd = wandb.run.dir if wandb.run else "."
            if step is None:
                step = "summary"
            if isinstance(val[0], Image):
                converted = Image.transform(val, cwd,
                                            "{}_{}.jpg".format(key, step))
            elif isinstance(val[0], Audio):
                converted = Audio.transform(val, cwd, key, step)
        elif any(is_image) or any(is_audio):
            raise ValueError(
                "Mixed media types in the same list aren't supported")
    elif isinstance(val, Histogram):
        converted = Histogram.transform(val)
    elif isinstance(val, Graph):
        if mode == "history":
            raise ValueError("Graphs are only supported in summary")
        converted = Graph.transform(val)
    elif isinstance(val, Table):
        converted = Table.transform(val)
    return converted


def to_json(payload, mode="history"):
    """Converts all keys in a potentially nested array into their JSON representation"""
    for key, val in six.iteritems(payload):
        if isinstance(val, dict):
            payload[key] = to_json(val, mode)
        else:
            payload[key] = val_to_json(
                key, val, mode, step=payload.get("_step"))
    return payload


class Graph(object):
    def __init__(self, format="keras"):
        self.format = format
        self.nodes = []
        self.nodes_by_id = {}
        self.edges = []
        self.loaded = False
        self.criterion = None
        self.criterion_passed = False
        self.root = None  # optional root Node if applicable

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
                if (len(v) > 1) or (len(v) == 1 and len(v[0].inbound_layers) > 1):
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
            graph.add_node(node)

            if hasattr(layers[i], '_inbound_nodes'):
                for in_node in layers[i]._inbound_nodes:
                    if relevant_nodes and in_node not in relevant_nodes:
                        # node is not part of the current network
                        continue
                    for in_layer in in_node.inbound_layers:
                        inbound_keras_node = Node.from_keras(in_layer)

                        if (inbound_keras_node.id not in graph.nodes_by_id):
                            graph.add_node(inbound_keras_node)
                        inbound_node = graph.nodes_by_id[inbound_keras_node.id]

                        graph.add_edge(inbound_node, node)

        return graph


    @staticmethod
    def transform(graph):
        return {"_type": "graph", "format": graph.format,
            "nodes": [Node.transform(node) for node in graph.nodes],
            "edges": [Edge.transform(edge) for edge in graph.edges]}


class Node(object):
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

    def __repr__(self):
        return str(self._attributes)

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

    @staticmethod
    def transform(node):
        return node._attributes


class Edge(object):
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

    @staticmethod
    def transform(edge):
        return [edge.from_node.id, edge.to_node.id]


class Histogram(object):
    MAX_LENGTH = 512

    def __init__(self, sequence=None, np_histogram=None, num_bins=64):
        """Accepts a sequence to be converted into a histogram or np_histogram can be set
        to a tuple of (values, bins_edges) as np.histogram returns i.e.

        wandb.log({"histogram": wandb.Histogram(np_histogram=np.histogram(data))})

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

    def to_json(self):
        return Histogram.transform(self)

    @staticmethod
    def transform(histogram):
        return {"_type": "histogram", "values": histogram.histogram, "bins": histogram.bins}


class Table(object):
    MAX_ROWS = 300

    def __init__(self, columns=["Input", "Output", "Expected"], rows=[]):
        self.columns = columns
        self.rows = list(rows)

    def add_row(self, *row):
        if len(row) != len(self.columns):
            raise ValueError("This table expects {} columns: {}".format(
                len(self.columns), self.columns))
        self.rows.append(list(row))

    @staticmethod
    def transform(table):
        if len(table.rows) > Table.MAX_ROWS:
            logging.warn(
                "The maximum number of rows to display per step is %i." % Table.MAX_ROWS)
        return {"_type": "table", "columns": table.columns, "data": table.rows[:Table.MAX_ROWS]}


class Audio(object):
    MAX_AUDIO_COUNT = 100

    def __init__(self, data, sample_rate=None, caption=None):
        """
        Accepts numpy array of audio data. 
        """
        if sample_rate == None:
            raise ValueError('Missing argument "sample_rate" in wandb.Audio')
        self.audio_data = data
        self.sample_rate = sample_rate
        self.caption = caption

    @staticmethod
    def transform(audio_list, out_dir, key, step):
        if len(audio_list) > Audio.MAX_AUDIO_COUNT:
            logging.warn(
                "The maximum number of audio files to store per step is %i." % Audio.MAX_AUDIO_COUNT)
        sf = util.get_module(
            "soundfile", required="wandb.Audio requires the soundfile package. To get it, run: pip install soundfile")
        base_path = os.path.join(out_dir, "media", "audio")
        util.mkdir_exists_ok(base_path)
        for i, audio in enumerate(audio_list[:Audio.MAX_AUDIO_COUNT]):
            sf.write(os.path.join(base_path, "{}_{}_{}.wav".format(key, step, i)), audio.audio_data, audio.sample_rate)
        meta = {"_type": "audio", "count": min(len(audio_list), Audio.MAX_AUDIO_COUNT)}
        sample_rates = Audio.sample_rates(audio_list[:Audio.MAX_AUDIO_COUNT])
        if sample_rates:
            meta["sampleRates"] = sample_rates
        durations = Audio.durations(audio_list[:Audio.MAX_AUDIO_COUNT])
        if durations:
            meta["durations"] = durations
        captions = Audio.captions(audio_list[:Audio.MAX_AUDIO_COUNT])
        if captions:
            meta["captions"] = captions
        return meta

    @staticmethod
    def durations(audio_list):
        durations = [(len(a.audio_data) / float(a.sample_rate)) for a in audio_list]
        return durations

    @staticmethod
    def sample_rates(audio_list):
        return [a.sample_rate for a in audio_list]

    @staticmethod
    def captions(audio_list):
        captions = [a.caption for a in audio_list]
        if all(c is None for c in captions):
            return False
        else:
            return ['' if c==None else c for c in captions]


class Image(object):
    MAX_IMAGES = 100

    def __init__(self, data, mode=None, caption=None, grouping=None):
        """
        Accepts numpy array of image data, or a PIL image. The class attempts to infer
        the data format and converts it.

        If grouping is set to a number the interface combines N images.
        """
        PILImage = util.get_module(
            "PIL.Image", required="wandb.Image requires the PIL package, to get it run: pip install pillow")
        if util.is_matplotlib_typename(util.get_full_typename(data)):
            buf = six.BytesIO()
            util.ensure_matplotlib_figure(data).savefig(buf)
            self.image = PILImage.open(buf)
        elif isinstance(data, PILImage.Image):
            self.image = data
        elif util.is_pytorch_tensor_typename(util.get_full_typename(data)):
            vis_util = util.get_module(
                "torchvision.utils", "torchvision is required to render images")
            if hasattr(data, "requires_grad") and data.requires_grad:
                data = data.detach()
            data = vis_util.make_grid(data, normalize=True)
            self.image = PILImage.fromarray(data.mul(255).clamp(
                0, 255).byte().permute(1, 2, 0).cpu().numpy())
        else:
            data = data.squeeze()  # get rid of trivial dimensions as a convenience
            self.image = PILImage.fromarray(
                self.to_uint8(data), mode=mode or self.guess_mode(data))
        self.grouping = grouping
        self.caption = caption

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

    def to_json(self):
        Image.transform([self], wandb.run.dir, "summary.jpg")

    @staticmethod
    def transform(images, out_dir, fname):
        """
        Combines a list of images into a single sprite returning meta information
        """
        from PIL import Image as PILImage
        base = os.path.join(out_dir, "media", "images")
        width, height = images[0].image.size
        if len(images) > Image.MAX_IMAGES:
            logging.warn(
                "The maximum number of images to store per step is %i." % Image.MAX_IMAGES)
        sprite = PILImage.new(
            mode='RGB',
            size=(width * len(images), height),
            color=(0, 0, 0, 0))
        for i, image in enumerate(images[:Image.MAX_IMAGES]):
            location = width * i
            sprite.paste(image.image, (location, 0))
        util.mkdir_exists_ok(base)
        sprite.save(os.path.join(base, fname), transparency=0)
        meta = {"width": width, "height": height,
                "count": len(images), "_type": "images"}
        # TODO: hacky way to enable image grouping for now
        grouping = images[0].grouping
        if grouping:
            meta["grouping"] = grouping
        captions = Image.captions(images[:Image.MAX_IMAGES])
        if captions:
            meta["captions"] = captions
        return meta

    @staticmethod
    def captions(images):
        if images[0].caption != None:
            return [i.caption for i in images]
        else:
            return False
