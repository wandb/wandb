#!/usr/bin/env python
# -*- coding: future_fstrings -*-


import collections
import pprint

import numpy


class Graph(object):
    def __init__(self):
        self.nodes = []
        self.nodes_by_id = {}
        self.edges = []

    def print(self):
        for edge in self.edges:
            pprint.pprint(edge.attributes)
        for node in self.nodes:
            pprint.pprint(node.attributes)

    def add_node(self, node=None, **node_kwargs):
        if node is None:
            node = Node(**node_kwargs)
        elif node_kwargs:
            raise ValueError(f'Only pass one of either node ({node}) or other keyword arguments ({node_kwargs})')
        self.nodes.append(node)
        assert node.id not in self.nodes_by_id
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
    def from_torch(cls, var, module=None):
        """Create a Graph from a PyTorch compute graph

        From https://github.com/szagoruyko/pytorchviz/blob/8960dbc6f3cbe8a6a5f0191f77f5d6e34a542d6b/torchviz/dot.py

        Produces Graphviz representation of PyTorch autograd graph.
        Blue nodes are the Variables that require grad, orange are Tensors
        saved for backward in torch.autograd.Function
        Args:
            var: output Variable
            params: dict of (name, Variable) to add names to node that
                require grad (TODO: make optional)
        """
        import torch

        if params is not None:
            assert all(isinstance(p, torch.autograd.Variable) for p in params.values())
            param_map = {id(v): k for k, v in params.items()}

        dot = cls()
        seen = set()

        def size_to_str(size):
            return '(' + (', ').join(['%d' % v for v in size]) + ')'

        output_nodes = (var.grad_fn,) if not isinstance(var, tuple) else tuple(v.grad_fn for v in var)

        def add_node(var):
            if id(var) in dot.nodes_by_id:
                return dot.nodes_by_id[id(var)]
            else:
                if torch.is_tensor(var):
                    # note: this used to show .saved_tensors in pytorch0.2, but stopped
                    # working as it was moved to ATen and Variable-Tensor merged
                    return dot.add_node(id=id(var), size=var.size())
                elif hasattr(var, 'variable'):
                    u = var.variable
                    name = param_map[id(u)] if params is not None else ''
                    return dot.add_node(id=id(var), name=name, size=u.size())
                elif var in output_nodes:
                    return dot.add_node(id=id(var), class_name=type(var).__name__, is_output=True)
                else:
                    return dot.add_node(id=id(var), class_name=type(var).__name__)


        def add_nodes(var):
            if var not in seen:
                var_node = add_node(var)
                seen.add(var)
                if hasattr(var, 'next_functions'):
                    for u in var.next_functions:
                        if u[0] is not None:
                            u_node = add_node(u[0])
                            dot.add_edge(u_node, var_node)
                            add_nodes(u[0])
                if hasattr(var, 'saved_tensors'):
                    for t in var.saved_tensors:
                        t_node = add_node(t)
                        dot.add_edge(t_node, var_node)
                        add_nodes(t)

        # handle multiple outputs
        if isinstance(var, tuple):
            for v in var:
                add_nodes(v.grad_fn)
        else:
            add_nodes(var.grad_fn)

        return dot

    @staticmethod
    def transform(graph):
        return {"_type": "graph", "format": "keras", "nodes": [Node.transform(node) for node in graph.nodes]}


class Node(object):
    def __init__(self, id=None, name=None, class_name=None, size=None, output_shape=None, is_output=None, num_parameters=None):
        self.attributes = {'name': None}
        self.out_edges = {}  # indexed by dest node id
        self.in_edges = {}  # indexed by source node id

        if id is not None:
            self.id = id
        if name is not None:
            self.name = name
        if class_name is not None:
            self.class_name = class_name
        if size is not None:
            self.size = size
        if output_shape is not None:
            self.output_shape = output_shape
        if is_output is not None:
            self.is_output = is_output

    @property
    def id(self):
        """Must be unique in the graph"""
        return self.attributes.get('id', self.name)

    @id.setter
    def id(self, val):
        self.attributes['id'] = val
        return val

    @property
    def name(self):
        """Optional, not necessarily unique"""
        return self.attributes.get('name')

    @name.setter
    def name(self, val):
        self.attributes['name'] = val
        return val

    @property
    def class_name(self):
        """Usually the type of layer or sublayer"""
        return self.attributes.get('class_name')

    @class_name.setter
    def class_name(self, val):
        self.attributes['class_name'] = val
        return val

    @property
    def size(self):
        return self.attributes.get('size')

    @size.setter
    def size(self, val):
        """Tensor size"""
        self.attributes['size'] = tuple(val)
        self.num_parameters = numpy.prod(self.size)
        return val

    @property
    def output_shape(self):
        return self.attributes.get('output_shape')

    @output_shape.setter
    def output_shape(self, val):
        """Tensor output_shape"""
        self.attributes['output_shape'] = val
        return val

    @property
    def is_output(self):
        return self.attributes.get('is_output')

    @is_output.setter
    def is_output(self, val):
        """Tensor is_output"""
        self.attributes['is_output'] = val
        return val

    @property
    def num_parameters(self):
        return self.attributes.get('num_parameters')

    @num_parameters.setter
    def num_parameters(self, val):
        """Tensor num_parameters"""
        self.attributes['num_parameters'] = val
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
        node.attributes['inbound_nodes'] = connections
        return node

    @staticmethod
    def transform(node):
        return node.attributes


class Edge(object):
    def __init__(self, from_node, to_node):
        pass
        self.attributes = {}
        self.from_node = from_node.id
        self.to_node = to_node.id

    @property
    def from_node(self):
        return self.attributes.get('from_node')

    @from_node.setter
    def from_node(self, val):
        self.attributes['from_node'] = val
        return val

    @property
    def to_node(self):
        return self.attributes.get('to_node')

    @to_node.setter
    def to_node(self, val):
        self.attributes['to_node'] = val
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
            try:
                import numpy as np
            except ImportError:
                raise ValueError(
                    "Auto creation of histograms requires numpy")
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
