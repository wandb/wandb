import itertools
import pprint
from six.moves import queue

import collections
import os
import logging
import six
import wandb
from wandb import util
from operator import mul
from six.moves import reduce


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
        self.nodes_by_id[from_node.id].out_edges[to_node.id] = edge
        self.nodes_by_id[to_node.id].in_edges[from_node.id] = edge

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
            node = Node.from_keras(layers[i], relevant_nodes)
            graph.add_node(node)

        return graph

    @classmethod
    def hook_torch(cls, model, criterion=None):
        graph = cls("torch")
        graph.hook_torch_modules(model, criterion)
        return graph

    def create_forward_hook(self, name, modules):
        graph = self

        def after_forward_hook(module, input, output):
            if id(module) in modules:
                return
            modules.add(id(module))
            if not isinstance(output, tuple):
                output = (output,)
            parameters = [(pname, list(param.size()))
                          for pname, param in module.named_parameters()]
            node = Node(
                id=id(module),
                name=name,
                class_name=str(module),
                output_shape=[list(o.shape) for o in output],
                parameters=parameters,
                num_parameters=[reduce(mul, size)
                                for (pname, size) in parameters]
            )
            graph.nodes_by_id[id(module)] = node
            for param in module.parameters():
                graph.nodes_by_id[id(param)] = node
            graph.add_node(node)
            if not graph.criterion_passed:
                graph.criterion = output[0].grad_fn
        return after_forward_hook

    def hook_torch_modules(self, module, criterion=None, prefix=None):
        torch = util.get_module("torch", "Could not import torch")
        hooks = []
        modules = set()
        layers = 0
        graph = self
        if criterion:
            graph.criterion = criterion
            graph.criterion_passed = True

        # TODO: We might be able to use `named_children()` here, need to verify the API in older version
        for name, sub_module in module._modules.items():
            name = name or str(layers)
            if prefix:
                name = prefix + "." + name
            layers += 1
            if not isinstance(sub_module, torch.nn.Module):
                # TODO: Why does this happen?
                break

            if isinstance(sub_module, (torch.nn.Container, torch.nn.Sequential)):
                #
                # nn.Container or nn.Sequential who have sub nn.Module. Recursively visit and hook their decendants.
                #
                self.hook_torch_modules(sub_module, prefix=name)
            else:
                def backward_hook(module, input, output):
                    [hook.remove() for hook in hooks]
                    graph.loaded = True
                    # TODO: Keeping this here as a starting point for adding graph data
                    if not graph.loaded:
                        def traverse(node, functions=[]):
                            if hasattr(node, 'grad_fn'):
                                node = node.grad_fn

                            if hasattr(node, 'variable'):
                                node = graph.nodes_by_id.get(id(node.variable))
                                if node:
                                    node.functions = list(functions)
                                    del functions[:]

                            if hasattr(node, 'next_functions'):
                                functions.append(type(node).__name__)
                                for f in node.next_functions:
                                    if f[0]:
                                        functions.append(type(f[0]).__name__)
                                        traverse(f[0], functions)

                            if hasattr(node, 'saved_tensors'):
                                for t in node.saved_tensors:
                                    traverse(t)
                        traverse(graph.criterion)

                hooks.append(
                    sub_module.register_forward_hook(self.create_forward_hook(name, modules)))
                hooks.append(
                    sub_module.register_backward_hook(backward_hook))

    @classmethod
    def from_torch_layers(cls, module_graph, variable):
        """Recover something like neural net layers from PyTorch Module's and the
        compute graph from a Variable.

        Example output for a multi-layer RNN. We confusingly assign shared embedding values
        to the encoder, but ordered next to the decoder.

        rnns.0.linear.module.weight_raw rnns.0
        rnns.0.linear.module.bias rnns.0
        rnns.1.linear.module.weight_raw rnns.1
        rnns.1.linear.module.bias rnns.1
        rnns.2.linear.module.weight_raw rnns.2
        rnns.2.linear.module.bias rnns.2
        rnns.3.linear.module.weight_raw rnns.3
        rnns.3.linear.module.bias rnns.3
        decoder.weight encoder
        decoder.bias decoder
        """
        # TODO: We're currently not using this, but I left it here incase we want to resurrect! - CVP
        torch = util.get_module("torch", "Could not import torch")

        module_nodes_by_hash = {id(n): n for n in module_graph.nodes}
        module_parameter_nodes = [
            n for n in module_graph.nodes if isinstance(n.obj, torch.nn.Parameter)]

        names_by_pid = {id(n.obj): n.name for n in module_parameter_nodes}

        reachable_param_nodes = module_graph[0].reachable_descendents()
        reachable_params = {}
        module_reachable_params = {}
        names = {}
        for pid, reachable_nodes in reachable_param_nodes.items():
            node = module_nodes_by_hash[pid]
            if not isinstance(node.obj, torch.nn.Module):
                continue
            module = node.obj
            reachable_params = {}  # by object id
            module_reachable_params[id(module)] = reachable_params
            names[node.name] = set()
            for reachable_hash in reachable_nodes:
                reachable = module_nodes_by_hash[reachable_hash]
                if isinstance(reachable.obj, torch.nn.Parameter):
                    param = reachable.obj
                    reachable_params[id(param)] = param
                    names[node.name].add(names_by_pid[id(param)])

        # we look for correspondences between sets of parameters used in subtrees of the
        # computation graph and sets of parameters contained in subtrees of the module
        # graph
        node_depths = {id(n): d for n, d in module_graph[0].descendent_bfs()}
        parameter_module_names = {}
        parameter_modules = {}
        for param_node in (n for n in module_graph.nodes if isinstance(n.obj, torch.nn.Parameter)):
            pid = id(param_node.obj)
            best_node = None
            best_depth = None
            best_reachable_params = None
            for node in module_graph.nodes:
                if not isinstance(node.obj, torch.nn.Module):
                    continue
                module = node.obj
                reachable_params = module_reachable_params[id(module)]
                if pid in reachable_params:
                    depth = node_depths[id(node)]
                    if best_node is None or (len(reachable_params), depth) <= (len(best_reachable_params), best_depth):
                        #print(param_node.name, node.name)
                        best_node = node
                        best_depth = depth
                        best_reachable_params = reachable_params

            parameter_modules[pid] = best_node
            parameter_module_names[param_node.name] = best_node.name

        # contains all parameters but only a minimal set of modules necessary
        # to contain them (and which ideally correspond to conceptual layers)
        reduced_module_graph = cls()
        rmg_ids = itertools.count()
        rmg_root = Node(id=next(rmg_ids), node=module_graph[0])
        reduced_module_graph.add_node(rmg_root)
        reduced_module_graph.root = rmg_root
        rmg_nodes_by_pid = {}

        module_nodes_by_pid = {id(n.obj): n for n in module_graph.nodes}

        compute_graph, compute_node_vars = cls.from_torch_compute_graph(
            variable)
        for node, _ in reversed(list(compute_graph[0].ancestor_bfs())):
            param = compute_node_vars.get(node.id)
            pid = id(param)
            if not isinstance(param, torch.nn.Parameter):
                continue
            if pid not in module_nodes_by_pid:
                # not all Parameters that occur in the compute graph come from the Module graph
                continue

            # add the nodes in the order we want to display them on the frontend
            mid = id(parameter_modules[pid].obj)
            if mid in rmg_nodes_by_pid:
                rmg_module = rmg_nodes_by_pid[mid]
            else:
                rmg_module = rmg_nodes_by_pid[mid] = Node(
                    id=next(rmg_ids), node=module_nodes_by_pid[mid])
                reduced_module_graph.add_node(rmg_module)
                reduced_module_graph.add_edge(rmg_root, rmg_module)

            rmg_param = Node(id=next(rmg_ids), node=module_nodes_by_pid[pid])
            rmg_nodes_by_pid[pid] = rmg_param
            reduced_module_graph.add_node(rmg_param)

            reduced_module_graph.add_edge(rmg_module, rmg_param)
        return reduced_module_graph

    @staticmethod
    def transform(graph):
        return {"_type": "graph", "format": graph.format, "nodes": [Node.transform(node) for node in graph.nodes]}


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
    def from_keras(cls, layer, relevant_nodes=None):
        node = cls()

        try:
            output_shape = layer.output_shape
        except AttributeError:
            output_shape = ['multiple']

        node.name = layer.name
        node.class_name = layer.__class__.__name__
        node.output_shape = output_shape
        node.num_parameters = layer.count_params()

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
        node._attributes['inbound_nodes'] = connections
        return node

    @classmethod
    def from_torch_module(cls, nid, module):
        numpy = util.get_module("numpy", "Could not import numpy")

        node = cls()
        node.id = nid
        node.child_parameters = 0
        for parameter in module.parameters():
            node.child_parameters += numpy.prod(parameter.size())
        node.class_name = type(module).__name__

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
