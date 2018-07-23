import collections


class Graph(object):
    def __init__(self):
        self.nodes = []

    @classmethod
    def from_keras(cls, model):
        graph = cls()

        # Shamelessly copied from keras/keras/utils/layer_utils.py

        if model.__class__.__name__ == 'Sequential':
            sequential_like = True
        elif not model._is_graph_network:
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
            output_shape = 'multiple'

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

    @staticmethod
    def transform(histogram):
        return {"_type": "histogram", "values": histogram.histogram, "bins": histogram.bins}
