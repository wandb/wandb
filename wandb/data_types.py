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
    if isinstance(val, Image):
        val = [val]

    if isinstance(val, collections.Sequence) and len(val) > 0:
        is_image = [isinstance(v, Image) for v in val]
        if all(is_image):
            cwd = wandb.run.dir if wandb.run else "."
            if step is None:
                step = "summary"
            converted = Image.transform(val, cwd,
                                        "{}_{}.jpg".format(key, step))
        elif any(is_image):
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
    def __init__(self):
        self.nodes = []

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
            node = Node.from_keras(layers[i], relevant_nodes)
            graph.nodes.append(node)

        return graph

    @staticmethod
    def transform(graph):
        return {"_type": "graph", "format": "keras", "nodes": [Node.transform(node) for node in graph.nodes]}


class Node(object):
    def __init__(self):
        self.attributes = {}

    @classmethod
    def from_keras(cls, layer, relevant_nodes=None):
        node = cls()

        try:
            output_shape = layer.output_shape
        except AttributeError:
            output_shape = ['multiple']

        node.attributes['name'] = layer.name
        node.attributes['class_name'] = layer.__class__.__name__
        node.attributes['output_shape'] = output_shape
        node.attributes['num_parameters'] = layer.count_params()

        connections = []
        if hasattr(layer, '_inbound_nodes'):
            for in_node in layer._inbound_nodes:
                if relevant_nodes and in_node not in relevant_nodes:
                    # node is not part of the current network
                    continue
                for i in range(len(in_node.inbound_layers)):
                    inbound_layer = in_node.inbound_layers[i].name
                    inbound_node_index = in_node.node_indices[i]
                    inbound_tensor_index = in_node.tensor_indices[i]
                    connections.append(inbound_layer +
                                       '[' + str(inbound_node_index) + '][' +
                                       str(inbound_tensor_index) + ']')
        node.attributes['inbound_nodes'] = connections
        return node

    @staticmethod
    def transform(node):
        return node.attributes


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
                "The maximum length of a histogram is %i" % MAX_LENGTH)
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
