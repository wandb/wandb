#!/usr/bin/env python
# -*- coding: future_fstrings -*-


import itertools
import pprint
import queue

import numpy
torch = None  # lazy import


class Graph(object):
    def __init__(self):
        self.nodes = []
        self.nodes_by_id = {}
        self.edges = []

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
    def from_torch_layers(cls, module, variable):
        g = cls.from_torch_module(module)
        h, node_vars = cls.from_torch_var(variable)

        g_parameter_nodes = [n for n in g.nodes if isinstance(n.obj, torch.nn.Parameter)]
        g_parameter_node_ids = set(n.id for n in g_parameter_nodes)
        g_parameters = [n.obj for n in g_parameter_nodes]
        g_parameter_ids = set(id(p) for p in g_parameters)
        g_tensor_ids = set(id(p.data) for p in g_parameters)
        param_names = {id(n.obj): n.name for n in g_parameter_nodes}

        h_parameter_nodes = [n for n in h.nodes if isinstance(node_vars.get(n.id), torch.nn.Parameter)]
        h_parameter_node_ids = set(n.id for n in h_parameter_nodes)
        h_parameters = [node_vars[n.id] for n in h_parameter_nodes]
        h_parameter_ids = set(id(p) for p in h_parameters)
        h_tensor_ids = set(id(p.data) for p in h_parameters)
        param_ancestors = [n for n in h[0].ancestors() if n.id in h_parameter_node_ids]

        def h_node_name(n):
            return param_names.get(id(node_vars.get(n.id)))

        g_nodes_by_hash = {id(n): n for n in g.nodes}

        param_ancestor_names = [h_node_name(n) for n in param_ancestors]
        reachable_param_nodes = g[0].reachable_descendents()
        reachable_params = {}
        module_reachable_params = {}
        names = {}
        for h, reachable_nodes in reachable_param_nodes.items():
            node = g_nodes_by_hash[h]
            if not isinstance(node.obj, torch.nn.Module):
                continue
            module = node.obj
            reachable_params = {}  # by object id
            module_reachable_params[id(module)] = reachable_params
            names[node.name] = set()
            for reachable_hash in reachable_nodes:
                reachable = g_nodes_by_hash[reachable_hash]
                if isinstance(reachable.obj, torch.nn.Parameter):
                    param = reachable.obj
                    reachable_params[id(param)] = param
                    names[node.name].add(param_names[id(param)])

        import pprint
        pprint.pprint(names)

        node_depths = {id(n): d for n, d in g[0].descendent_bfs()}
        param_nodes = {id(n.obj): n for n in g_parameter_nodes}
        g_nodes = {id(n): n for n in g.nodes}
        parameter_modules = {}
        for param_h, param_node in param_nodes.items():
            best_node = None
            best_depth = None
            best_reachable_params = None
            for node in g.nodes:
                if not isinstance(node.obj, torch.nn.Module):
                    continue
                module = node.obj
                reachable_params = module_reachable_params[id(module)]
                if param_h in reachable_params:
                    depth = node_depths[id(node)]
                    if best_node is None or (len(reachable_params), depth) <= (len(best_reachable_params), best_depth):
                        print(param_node.name, node.name)
                        best_node = node
                        best_depth = depth
                        best_reachable_params = reachable_params

            parameter_modules[param_node.name] = best_node.name

        for param, module in parameter_modules.items():
            print(module, param)

        pprint.pprint(parameter_modules)


    @classmethod
    def from_torch_module(cls, root_module):
        """Create a Module-Parameter graph from a PyTorch Module
        """
        global torch
        import torch

        node_ids = itertools.count()

        root_node = Node.from_torch_module(next(node_ids), root_module)
        nodes_by_obj_id = { id(root_module): root_node }  # indexed by object identity

        graph = cls()
        graph.add_node(root_node)

        def add_module(module):
            node = nodes_by_obj_id[id(module)]

            for name, child in sorted(module.named_children()):
                if id(child) in nodes_by_obj_id:
                    child_node = nodes_by_obj_id[id(child)]
                else:
                    if node.name:
                        name = node.name + '.' + name

                    child_node = Node.from_torch_module(next(node_ids), child)
                    child_node.name = name
                    child_node.obj = child
                    nodes_by_obj_id[id(child)] = child_node
                    graph.add_node(child_node)
                    add_module(child)

                edge = graph.add_edge(node, child_node)
                edge.name = name

            for name, child in sorted(module.named_parameters()):
                if '.' in name:
                    """
                    We use this hack to avoid adding Param's that are inside ModuleList's
                    and ModuleDict's. They should be considered children of their
                    respective modules, not of this one. It's possible we'll make mistakes
                    if the Param's name has dots in it.

                    TODO(adrian): check / fix this

                    Here's how a ModuleList should behave:
                    param rnns.3.linear.param bias
                    param rnns.3.linear.param weight_raw

                    Here are some incorrect cases we're preventing:
                    dropping param rnns.3.linear param.bias
                    dropping param rnns.3.linear param.weight_raw
                    dropping param rnns.3 linear.param.bias
                    dropping param rnns.3 linear.param.weight_raw
                    """
                    #print('dropping param', node.name, name)
                    continue
                #print('param', node.name, name)

                if id(child) in nodes_by_obj_id:
                    child_node = nodes_by_obj_id[id(child)]
                else:
                    if node.name:
                        name = node.name + '.' + name

                    child_node = Node()
                    child_node.id = next(node_ids)
                    child_node.name = name
                    child_node.class_name = type(child).__name__
                    child_node.size = tuple(child.size())
                    child_node.num_parameters = numpy.prod(child.size())
                    child_node.obj = child  # XXX should only do this for debugging because it'll mess up garbage collection

                    nodes_by_obj_id[id(child)] = child_node
                    graph.add_node(child_node)

                edge = graph.add_edge(node, child_node)
                edge.name = name

        add_module(root_module)

        return graph

    @classmethod
    def from_torch_var(cls, var):
        """Create a Graph from a PyTorch compute graph

        From https://github.com/szagoruyko/pytorchviz/blob/8960dbc6f3cbe8a6a5f0191f77f5d6e34a542d6b/torchviz/dot.py

        Produces Graph from a PyTorch autograd graph.
        Nodes are the Variables that require gradients and the Tensors
        saved for backpropagation in torch.autograd.Function
        Args:
            var: Variable (eg. loss) for which to create a compute graph
        """
        global torch
        import torch

        graph = cls()
        seen = set()
        node_ids = itertools.count()
        nodes_by_var_id = {}
        # we keep this separate because we want to be able to keep the graph around but let this be garbage collected
        node_vars = {}

        def size_to_str(size):
            return '(' + (', ').join(['%d' % v for v in size]) + ')'

        output_nodes = (id(var.grad_fn),) if not isinstance(var, tuple) else tuple(id(v.grad_fn) for v in var)

        def add_node(var):
            orig_var = var
            if hasattr(var, 'variable'):
                var = var.variable

            if id(var) not in nodes_by_var_id:
                node = Node()

                node.id = next(node_ids)
                node.class_name = type(orig_var).__name__
                node_vars[node.id] = var

                if id(var) in output_nodes:
                    node.is_output = True

                if hasattr(var, 'size'):
                    node.size = var.size()

                if torch.is_tensor(var) and not (hasattr(var, 'requires_grad') and var.requires_grad):
                    # note: this used to show .saved_tensors in pytorch0.2, but stopped
                    # working as it was moved to ATen and Variable-Tensor merged
                    node.is_constant = True

                nodes_by_var_id[id(var)] = node

                graph.add_node(node)

            return nodes_by_var_id[id(var)]

        def add_nodes(var):
            if var not in seen:
                var_node = add_node(var)
                seen.add(var)
                if hasattr(var, 'next_functions'):
                    for u in var.next_functions:
                        if u[0] is not None:
                            u_node = add_node(u[0])
                            graph.add_edge(u_node, var_node)
                            add_nodes(u[0])
                if hasattr(var, 'saved_tensors'):
                    for t in var.saved_tensors:
                        t_node = add_node(t)
                        graph.add_edge(t_node, var_node)
                        add_nodes(t)

        # handle multiple outputs
        if isinstance(var, tuple):
            for v in var:
                add_nodes(v.grad_fn)
        else:
            add_nodes(var.grad_fn)

        return graph, node_vars

    @staticmethod
    def transform(graph):
        return {"_type": "graph", "format": "keras", "nodes": [Node.transform(node) for node in graph.nodes]}


class Node(object):
    def __init__(self, id=None, name=None, class_name=None, size=None, output_shape=None, is_output=None, num_parameters=None):
        self._attributes = {'name': None}
        self.in_edges = {}  # indexed by source node id
        self.out_edges = {}  # indexed by dest node id
        # optional object (eg. PyTorch Parameter or Module) that this Node represents
        self.obj = None

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
        if num_parameters is not None:
            self.num_parameters = num_parameters

    def __repr__(self):
        return str((self._attributes, list(self.in_edges.keys()), list(self.out_edges.keys())))

    def descendents(self):
        """Get descedents topologically sorted"""
        nodes = []
        self._add_descendents(set(), nodes, self)
        return nodes

    def _add_descendents(self, visited_ids, nodes, node):
        visited_ids.add(node.id)
        nodes.append(node)
        for edge in node.out_edges.values():
            if edge.to_node.id not in visited_ids:
                self._add_descendents(visited_ids, nodes, edge.to_node)

    def reachable_descendents(self, by_node=None):
        if by_node is None:
            by_node = {}

        h = id(self)
        if h not in by_node:
            by_node[h] = set([h])
            for edge in self.out_edges.values():
                edge.to_node.reachable_descendents(by_node=by_node)
                by_node[h] |= by_node[id(edge.to_node)]

        return by_node

    def descendent_bfs(self):
        q = queue.Queue()
        q.put(self)
        node_depths = {id(self): 0}
        while not q.empty():
            node = q.get()
            depth = node_depths[id(node)]
            yield node, depth
            for edge in node.out_edges.values():
                h = id(edge.to_node)
                if h in node_depths:
                    node_depths[h] = min(node_depths[h], depth + 1)
                else:
                    node_depths[h] = depth + 1
                    q.put(edge.to_node)


    def descendent_dfs(self):
        visited_nodes = set([id(self)])
        node = self
        yield node
        edge_iter = iter(self.out_edges.values())
        node_edges_stack = [(node, edge_iter)]
        while node_edges_stack:
            node, edge_iter = node_edges_stack[-1]
            try:
                edge = next(edge_iter)
            except StopIteration:
                # We'll hit this when there are no edges left to iterate over.
                # When we've added a node to the stack we break out of the loop
                # above, but won't run this block.
                node_edges_stack.pop()
            else:
                if id(edge.to_node) not in visited_nodes:
                    node = edge.to_node
                    yield node
                    edge_iter = iter(node.out_edges.values())
                    visited_nodes.add(id(node))
                    node_edges_stack.append((node, edge_iter))

    def ancestors(self):
        """Get descedents topologically sorted"""
        nodes = []
        self._add_ancestors(set(), nodes, self)
        return nodes

    def _add_ancestors(self, visited_ids, nodes, node):
        visited_ids.add(node.id)
        nodes.append(node)
        for edge in node.in_edges.values():
            if edge.from_node.id not in visited_ids:
                self._add_ancestors(visited_ids, nodes, edge.from_node)

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
    def size(self):
        return self._attributes.get('size')

    @size.setter
    def size(self, val):
        """Tensor size"""
        self._attributes['size'] = tuple(val)
        self.num_parameters = numpy.prod(self.size)
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
        global torch
        import torch

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
