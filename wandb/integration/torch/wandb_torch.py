"""PyTorch-specific functionality."""

import itertools
from functools import reduce
from operator import mul
from typing import TYPE_CHECKING, List

import wandb
from wandb import util
from wandb.data_types import Node

torch = None

if TYPE_CHECKING:
    from torch import Tensor
    from torch.nn import Module


def nested_shape(array_or_tuple, seen=None):
    """Figure out the shape of tensors possibly embedded in tuples.

    for example:
    - [0,0] returns (2)
    - ([0,0], [0,0]) returns (2,2)
    - (([0,0], [0,0]),[0,0]) returns ((2,2),2).
    """
    if seen is None:
        seen = set()
    if hasattr(array_or_tuple, "size"):
        # pytorch tensors use V.size() to get size of tensor
        return list(array_or_tuple.size())
    elif hasattr(array_or_tuple, "get_shape"):
        # tensorflow uses V.get_shape() to get size of tensor
        return array_or_tuple.get_shape().as_list()
    elif hasattr(array_or_tuple, "shape"):
        return array_or_tuple.shape

    seen.add(id(array_or_tuple))
    try:
        # treat object as iterable
        return [
            nested_shape(item, seen) if id(item) not in seen else 0
            for item in list(array_or_tuple)
        ]
    except TypeError:
        # object is not actually iterable
        # LB: Maybe we should throw an error?
        return []


LOG_TRACK_COUNT, LOG_TRACK_THRESHOLD = range(2)


def log_track_init(log_freq: int) -> List[int]:
    """Create tracking structure used by log_track_update."""
    log_track = [0, 0]
    log_track[LOG_TRACK_THRESHOLD] = log_freq
    return log_track


def log_track_update(log_track: int) -> bool:
    """Count (log_track[0]) up to threshold (log_track[1]), reset count (log_track[0]) and return true when reached."""
    log_track[LOG_TRACK_COUNT] += 1
    if log_track[LOG_TRACK_COUNT] < log_track[LOG_TRACK_THRESHOLD]:
        return False
    log_track[LOG_TRACK_COUNT] = 0
    return True


class TorchHistory:
    """History methods specific to PyTorch."""

    def __init__(self):
        global torch
        torch = wandb.util.get_module("torch", "Could not import torch")
        self._hook_handles = {}
        self._num_bins = 64
        self._is_cuda_histc_supported = None
        self.hook_torch = TorchGraph.hook_torch

    def add_log_parameters_hook(
        self,
        module: "Module",
        name: str = "",
        prefix: str = "",
        log_freq: int = 0,
    ) -> None:
        """This instruments hooks into the pytorch module.

        log parameters after a forward pass
        log_freq - log gradients/parameters every N batches.
        """
        # if name is not None:
        prefix = prefix + name

        if not hasattr(module, "_wandb_hook_names"):
            module._wandb_hook_names = []

        def parameter_log_hook(module, input_, output, log_track):
            if not log_track_update(log_track):
                return
            for name, parameter in module.named_parameters():
                # for pytorch 0.3 Variables
                if isinstance(parameter, torch.autograd.Variable):
                    data = parameter.data
                else:
                    data = parameter
                self.log_tensor_stats(data.cpu(), "parameters/" + prefix + name)

        log_track_params = log_track_init(log_freq)
        try:
            hook = module.register_forward_hook(
                lambda mod, inp, outp: parameter_log_hook(
                    mod, inp, outp, log_track_params
                )
            )
            self._hook_handles["parameters/" + prefix] = hook
            module._wandb_hook_names.append("parameters/" + prefix)
        except RuntimeError as e:
            wandb.termwarn(
                f"Trying to register forward_hook failed ({e}) - skipping parameter tracking."
            )

    def add_log_gradients_hook(
        self,
        module: "Module",
        name: str = "",
        prefix: str = "",
        log_freq: int = 0,
    ) -> None:
        """This instruments hooks into the PyTorch module slog gradients after a backward pass.

        Args:
            module: torch.nn.Module - the module to instrument
            name: str - the name of the module
            prefix: str - the prefix to add to the name
            log_freq: log gradients/parameters every N batches
        """
        # if name is not None:
        prefix = prefix + name

        if not hasattr(module, "_wandb_hook_names"):
            module._wandb_hook_names = []

        for name, parameter in module.named_parameters():
            if parameter.requires_grad:
                log_track_grad = log_track_init(log_freq)
                module._wandb_hook_names.append("gradients/" + prefix + name)
                self._hook_variable_gradient_stats(
                    parameter, "gradients/" + prefix + name, log_track_grad
                )

    def log_tensor_stats(self, tensor, name):  # noqa: C901
        """Add distribution statistics on a tensor's elements to the current History entry."""
        # TODO Handle the case of duplicate names.
        if isinstance(tensor, (tuple, list)):
            while isinstance(tensor, (tuple, list)) and isinstance(
                tensor[0], (tuple, list)
            ):
                tensor = [item for sublist in tensor for item in sublist]
            tensor = torch.cat([t.detach().clone().reshape(-1) for t in tensor])

        tensor = tensor.detach().clone()
        # checking for inheritance from _TensorBase didn't work for some reason
        if not hasattr(tensor, "shape"):
            cls = type(tensor)
            raise TypeError(f"Expected Tensor, not {cls.__module__}.{cls.__name__}")

        # Sparse tensors have a bunch of implicit zeros. In order to histo them correctly,
        # we have to count them up and add them to the histo ourselves.
        sparse_zeros = None
        if tensor.is_sparse:
            # Have to call this on a sparse tensor before most other ops.
            tensor = tensor.cpu().coalesce()

            backing_values = tensor._values()
            sparse_zeros = tensor.numel() - backing_values.numel()
            tensor = backing_values

        flat = tensor.reshape(-1)

        if flat.is_cuda:
            if self._is_cuda_histc_supported is None:
                try:
                    flat.histc(bins=self._num_bins)
                except RuntimeError:
                    self._is_cuda_histc_supported = False
                else:
                    self._is_cuda_histc_supported = True

            # As of torch 1.0.1.post2+nightly, float16 cuda summary ops are not supported (convert to float32)
            if not self._is_cuda_histc_supported:
                flat = flat.cpu()
            elif not isinstance(
                flat, (torch.cuda.FloatTensor, torch.cuda.DoubleTensor)
            ):
                flat = flat.type(torch.cuda.FloatTensor)

        # Since we use histc, we need to make sure that torch supports the operation on CPU,
        # otherwise we'll get a runtime error. Hence, we need to upcast to float32.
        if not flat.is_cuda and not isinstance(
            flat, (torch.FloatTensor, torch.DoubleTensor)
        ):
            flat = flat.type(torch.FloatTensor)

        # Skip logging if all values are nan or inf or the tensor is empty.
        if self._no_finite_values(flat):
            return

        # Remove nans and infs if present. There's no good way to represent that in histograms.
        flat = self._remove_infs_nans(flat)

        tmin = flat.min().item()
        tmax = flat.max().item()
        if sparse_zeros:
            # If we've got zeros to add in, make sure zero is in the hist range.
            tmin = 0 if tmin > 0 else tmin
            tmax = 0 if tmax < 0 else tmax
        # Anecdotally, this can somehow happen sometimes. Maybe a precision error
        # in min()/max() above. Swap here to prevent a runtime error.
        # If all values are equal, just return a single bin.
        if tmin > tmax:
            tmin, tmax = tmax, tmin
        if tmin == tmax:
            tensor = torch.Tensor([flat.numel()])
            tensor = tensor.cpu().clone().detach()
            bins = torch.Tensor([tmin, tmax])
        else:
            tensor = flat.histc(bins=self._num_bins, min=tmin, max=tmax)
            tensor = tensor.cpu().detach().clone()
            bins = torch.linspace(tmin, tmax, steps=self._num_bins + 1)

        # Add back zeroes from a sparse tensor.
        if sparse_zeros:
            bins_np = bins.numpy()
            tensor_np = tensor.numpy()
            bin_idx = 0
            num_buckets = len(bins_np) - 1
            for i in range(num_buckets):
                start = bins_np[i]
                end = bins_np[i + 1]
                # There are 3 cases to consider here, all of which mean we've found the right bucket
                # 1. The bucket range contains zero.
                # 2. The bucket range lower bound *is* zero.
                # 3. This is the last bucket and the bucket range upper bound is zero.
                if (start <= 0 and end > 0) or (i == num_buckets - 1 and end == 0):
                    bin_idx = i
                    break

            tensor_np[bin_idx] += sparse_zeros
            tensor = torch.Tensor(tensor_np)
            bins = torch.Tensor(bins_np)

        wandb.run._log(
            {name: wandb.Histogram(np_histogram=(tensor.tolist(), bins.tolist()))},
            commit=False,
        )

    def _hook_variable_gradient_stats(self, var, name, log_track):
        """Logs a Variable's gradient's distribution statistics next time backward() is called on it."""
        if not isinstance(var, torch.autograd.Variable):
            cls = type(var)
            raise TypeError(
                f"Expected torch.Variable, not {cls.__module__}.{cls.__name__}"
            )

        handle = self._hook_handles.get(name)
        if handle is not None and self._torch_hook_handle_is_valid(handle):
            raise ValueError(f'A hook has already been set under name "{name}"')

        def _callback(grad, log_track):
            if not log_track_update(log_track):
                return
            self.log_tensor_stats(grad.data, name)

        handle = var.register_hook(lambda grad: _callback(grad, log_track))
        self._hook_handles[name] = handle
        return handle

    def unhook_all(self):
        for handle in self._hook_handles.values():
            handle.remove()
        self._hook_handles = {}

    def unhook(self, name):
        handle = self._hook_handles.pop(name)
        handle.remove()

    def _torch_hook_handle_is_valid(self, handle):
        d = handle.hooks_dict_ref()
        if d is None:
            return False
        else:
            return handle.id in d

    def _no_finite_values(self, tensor: "Tensor") -> bool:
        return tensor.shape == torch.Size([0]) or (~torch.isfinite(tensor)).all().item()

    def _remove_infs_nans(self, tensor: "Tensor") -> "Tensor":
        if not torch.isfinite(tensor).all():
            tensor = tensor[torch.isfinite(tensor)]

        return tensor


class TorchGraph(wandb.data_types.Graph):
    def __init__(self):
        super().__init__("torch")
        self._graph_hooks = set()

    @classmethod
    def hook_torch(cls, model, criterion=None, graph_idx=0):
        wandb.termlog("logging graph, to disable use `wandb.watch(log_graph=False)`")
        graph = TorchGraph()
        graph.hook_torch_modules(model, criterion, graph_idx=graph_idx)
        return graph

    def create_forward_hook(self, name, graph_idx):
        graph = self

        def after_forward_hook(module, input, output):
            if id(module) not in self._graph_hooks:
                # hook already processed -> noop
                return
            if not isinstance(output, tuple):
                output = (output,)
            parameters = [
                (pname, list(param.size()))
                for pname, param in module.named_parameters()
            ]

            node = Node(
                id=id(module),
                name=name,
                class_name=str(module),
                output_shape=nested_shape(output),
                parameters=parameters,
                num_parameters=[reduce(mul, size, 1) for (pname, size) in parameters],
            )
            graph.nodes_by_id[id(module)] = node
            for param in module.parameters():
                graph.nodes_by_id[id(param)] = node
            graph.add_node(node)
            if not graph.criterion_passed:
                if hasattr(output[0], "grad_fn"):
                    graph.criterion = output[0].grad_fn
                elif (
                    isinstance(output[0], list)
                    and output[0]
                    and hasattr(output[0][0], "grad_fn")
                ):
                    graph.criterion = output[0][0].grad_fn

            # hook has been processed
            self._graph_hooks -= {id(module)}

            if not self._graph_hooks:
                # we went through the entire graph
                wandb.run.summary[f"graph_{graph_idx}"] = self

        return after_forward_hook

    def hook_torch_modules(
        self, module, criterion=None, prefix=None, graph_idx=0, parent=None
    ):
        torch = util.get_module("torch", "Could not import torch")
        layers = 0
        graph = self
        if hasattr(module, "_wandb_watch_called") and module._wandb_watch_called:
            raise ValueError(
                "You can only call `wandb.watch` once per model.  Pass a new instance of the model if you need to call wandb.watch again in your code."
            )
        module._wandb_watch_called = True
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
            module_types = [
                getattr(torch.nn, module_classname)
                for module_classname in (
                    "Container",
                    "Sequential",
                    "ModuleList",
                    "ModuleDict",
                )
                if hasattr(torch.nn, module_classname)
            ]
            if parent is None:
                parent = module

            if isinstance(sub_module, tuple(module_types)):
                self.hook_torch_modules(sub_module, prefix=name, parent=parent)
            else:
                self._graph_hooks |= {id(sub_module)}
                try:
                    graph_hook = sub_module.register_forward_hook(
                        self.create_forward_hook(name, graph_idx)
                    )
                    wandb.run._torch._hook_handles[
                        "topology/" + str(id(graph_hook))
                    ] = graph_hook
                    if not hasattr(parent, "_wandb_hook_names"):
                        # should never happen but let's be extra safe
                        parent._wandb_hook_names = []
                    parent._wandb_hook_names.append("topology/" + str(id(graph_hook)))
                except RuntimeError as e:
                    wandb.termwarn(
                        f"Trying to register forward_hook failed ({e}) - skipping graph tracking.",
                        repeat=False,
                    )

    @classmethod
    def from_torch_layers(cls, module_graph, variable):
        """Recover something like neural net layers from PyTorch Module's and the compute graph from a Variable.

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
        # TODO: We're currently not using this, but I left it here in case we want to resurrect! - CVP
        torch = util.get_module("torch", "Could not import torch")

        module_nodes_by_hash = {id(n): n for n in module_graph.nodes}
        module_parameter_nodes = [
            n for n in module_graph.nodes if isinstance(n.obj, torch.nn.Parameter)
        ]

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
        for param_node in (
            n for n in module_graph.nodes if isinstance(n.obj, torch.nn.Parameter)
        ):
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
                    if best_node is None or (len(reachable_params), depth) <= (
                        len(best_reachable_params),
                        best_depth,
                    ):
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

        compute_graph, compute_node_vars = cls.from_torch_compute_graph(variable)
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
                    id=next(rmg_ids), node=module_nodes_by_pid[mid]
                )
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
