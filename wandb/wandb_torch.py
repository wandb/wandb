#!/usr/bin/env python

"""PyTorch-specific functionality
"""

from collections import namedtuple
import weakref
from six.moves import reduce
from distutils.version import LooseVersion
from operator import mul


from wandb import util
from wandb.data_types import Node, Edge
import wandb

torch = None


def nested_shape(array_or_tuple):
    """Figures out the shape of tensors possibly embedded in tuples
     i.e 
     [0,0] returns (2)
     ([0,0], [0,0]) returns (2,2)
     (([0,0], [0,0]),[0,0]) returns ((2,2),2)
     """
    if hasattr(array_or_tuple, 'size'):
        # pytorch tensors use V.size() to get size of tensor
        return list(array_or_tuple.size())
    elif hasattr(array_or_tuple, 'get_shape'):
        # tensorflow uses V.get_shape() to get size of tensor
        return array_or_tuple.get_shape().as_list()
    elif hasattr(array_or_tuple, 'shape'):
        return array_or_tuple.shape

    try:
        #treat object as iterable
        return [nested_shape(item) for item in list(array_or_tuple)]
    except TypeError:
        # object is not actually iterable
        # LB: Maybe we should throw an error?
        return []

class TorchHistory(object):
    """History methods specific to PyTorch
    """

    def __init__(self, history):
        global torch
        torch = wandb.util.get_module("torch", "Could not import torch")
        self._history = weakref.ref(history)
        self._hook_handles = {}

    def add_log_hooks_to_pytorch_module(self, module, name=None, prefix='', log_parameters=True, log_gradients=True):
        """ This instuments hooks into the pytorch module
        log_parameters - log parameters after a forward pass
        log_gradients - log gradients after a backward pass
        """
        if name is not None:
            prefix = prefix + name

        def parameter_log_hook(module, input_, output):
            for name, parameter in module.named_parameters():
                # for pytorch 0.3 Variables
                if isinstance(parameter, torch.autograd.Variable):
                    data = parameter.data
                else:
                    data = parameter
                self.log_tensor_stats(data, 'parameters/' + prefix + name)

        if log_parameters:
            module.register_forward_hook(parameter_log_hook)

        # This won't handle the case if the network changes
        if log_gradients:
            for name, parameter in module.named_parameters():
                if parameter.requires_grad:
                    self._hook_variable_gradient_stats(
                        parameter, 'gradients/' + prefix + name)


    def log_module_stats(self, module, name):
        self._hook_module_input_output_stats(module, name)
        self._hook_module_input_output_gradient_stats(module, name)
        for child_name, child in module.named_children():
            self.log_module_stats(child, name + '.' + child_name)

    def log_tensor_stats(self, tensor, name):
        """Add distribution statistics on a tensor's elements to the current History entry
        """

        # LB We could potentially speed this up by using pytorch's torch.histc instead of
        # converting to numpy
        # TODO Handle the case of duplicate names.

        if (isinstance(tensor, tuple) or isinstance(tensor, list)):
            while (isinstance(tensor, tuple) or isinstance(tensor, list)) and (isinstance(tensor[0], tuple) or isinstance(tensor[0], list)):
                tensor = [item for sublist in tensor for item in sublist]
            tensor = torch.cat([t.view(-1) for t in tensor])

        # checking for inheritance from _TensorBase didn't work for some reason
        if not hasattr(tensor, 'shape'):
            cls = type(tensor)
            raise TypeError('Expected Tensor, not {}.{}'.format(
                cls.__module__, cls.__name__))
        history = self._history()
        if history is None or not history.compute:
            return
        flat = tensor.view(-1)

        # detach is new in 0.4
        tensor = flat.cpu().clone()
        if (hasattr(tensor, "detach")):
            tensor = tensor.detach()
        else:
            tensor = tensor.numpy()

        history.row.update({
            name: wandb.Histogram(tensor)
        })

    def _hook_variable_gradient_stats(self, var, name):
        """Logs a Variable's gradient's distribution statistics next time backward()
        is called on it.
        """
        if not isinstance(var, torch.autograd.Variable):
            cls = type(var)
            raise TypeError('Expected torch.Variable, not {}.{}'.format(
                cls.__module__, cls.__name__))

        handle = self._hook_handles.get(name)
        if handle is not None and self._torch_hook_handle_is_valid(handle):
            raise ValueError(
                'A hook has already been set under name "{}"'.format(name))

        def _callback(grad):
            #_callback()
            self.log_tensor_stats(grad.data, name)
            # self.unhook(name)

        handle = var.register_hook(_callback)
        self._hook_handles[name] = handle
        return handle

    def unhook(self, name):
        handle = self._hook_handles.pop(name)
        handle.remove()


    def _torch_hook_handle_is_valid(handle):
        d = handle.hooks_dict_ref()
        if d is None:
            return False
        else:
            return handle.id in d

class TorchGraph(wandb.data_types.Graph):
       
    def __init__(self):
        super(TorchGraph, self).__init__("torch") 

    @classmethod
    def hook_torch(cls, model, criterion=None):
        graph = TorchGraph()
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
                output_shape=nested_shape(output),
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

        for name, sub_module in module.named_children():
            name = name or str(layers)
            if prefix:
                name = prefix + "." + name
            layers += 1
            if not isinstance(sub_module, torch.nn.Module):
                # TODO: Why does this happen?
                break

            # Trying to support torch >0.3 making this code complicated
            # We want a list of types that we should recurse into
            # Torch 0.3   uses containers
            #       0.4   has ModuleList
            #       0.4.1 has ModuleDict
            module_types = [getattr(torch.nn, module_classname)
                for module_classname in ("Container", "Sequential", "ModuleList", "ModuleDict")
                if hasattr(torch.nn, module_classname)]
                   
            if isinstance(sub_module, tuple(module_types)):
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

    @classmethod
    def node_from_module(cls, nid, module):
        numpy = util.get_module("numpy", "Could not import numpy")

        node = wandb.Node()
        node.id = nid
        node.child_parameters = 0
        for parameter in module.parameters():
            node.child_parameters += numpy.prod(parameter.size())
        node.class_name = type(module).__name__

        return node
