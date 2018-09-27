#!/usr/bin/env python

"""PyTorch-specific functionality
"""

from collections import namedtuple
import weakref

from distutils.version import LooseVersion
import wandb
torch = None  # gets imported lazily by import_torch()

HOOKS = None


def init_torch():
    """Lazily import PyTorch only when we need it to instantiate TorchHistory or something
    """
    global torch, HOOKS
    import torch
    #HOOKS = TorchHooks()


class TorchHistory(object):
    """History methods specific to PyTorch
    """

    def __init__(self, history):
        init_torch()
        self._history = weakref.ref(history)
        self._hook_handles = {}

    def log_stats(self, variable_or_module, name=None, prefix='', values=True, gradients=True):
        """Log distribution statistics for a torch Variable or Module and its next
        gradient in History.

        For a Variable, logs statistics on its current data and gradient whenever
        its backward() method is next called. For a module, logs the same on all
        its Parameters (including those of submodules).

        Here's how you might use this function to instrument the hidden units of a
        network:

            def forward(self, x):
                x = F.relu(F.max_pool2d(self.conv1(x), 2))
                run.history.torch.log_stats(x, 'conv1.out')
                x = F.relu(F.max_pool2d(self.conv2_drop(self.conv2(x)), 2))
                run.history.torch.log_stats(x, 'conv2.out')
                x = x.view(-1, args.n2 * 16)
                x = F.relu(self.fc1(x))
                run.history.torch.log_stats(x, 'fc1.out')
                x = F.dropout(x, training=self.training)
                x = self.fc2(x)
                x = F.log_softmax(x, dim=0)
                run.history.torch.log_stats(x, 'fc2.out')
                return x
        """
        history = self._history()
        if history is None or not history.compute:
            return
        if name is None:
            name = ''

        if isinstance(variable_or_module, torch.autograd.Variable):
            if name is None:
                raise wandb.Error('Need a name to log stats for a Variable.')
            var = variable_or_module
            if values:
                self.log_tensor_stats(var.data, prefix + name)
            if gradients:
                self._hook_variable_gradient_stats(
                    var, prefix + name + ':grad')
        elif isinstance(variable_or_module, torch.nn.Module):
            module = variable_or_module
            if name is not None:
                prefix = prefix + name
            self.log_module_stats(module, prefix)
        else:
            cls = type(var)
            raise TypeError('Expected torch.autograd.Variable or torch.nn.Module, not {}.{}'.format(
                cls.__module__, cls.__name__))

    def log_module_parameters(self, module, name=None, prefix='', values=True, gradients=True):
        if name is not None:
            prefix = prefix + name
        for name, parameter in module.named_parameters():
            self.log_stats(parameter, name=name, prefix=prefix,
                           values=values, gradients=gradients)

    def log_module_stats(self, module, name):
        self._hook_module_input_output_stats(module, name)
        self._hook_module_input_output_gradient_stats(module, name)
        for child_name, child in module.named_children():
            self.log_module_stats(child, name + '.' + child_name)


    def log_tensor_stats(self, tensor, name):
        """Add distribution statistics on a tensor's elements to the current History entry
        """
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
        #wandb.termlog(name)
        history.row.update({
            name: wandb.Histogram(flat.cpu().clone().detach())
        })

    def _hook_module_input_output_stats(self, module, name):
        if not isinstance(module, torch.nn.Module):
            cls = type(module)
            raise TypeError('Expected torch.nn.Module, not {}.{}'.format(
                cls.__module__, cls.__name__))
        hook_name = name + ':io'
        input_name = name + ':input'
        output_name = name + ':output'

        handle = self._hook_handles.get(hook_name)
        if handle is not None and _torch_hook_handle_is_valid(handle):
            raise ValueError(
                'A hook has already been set under name "{}"'.format(hook_name))

        def _hook(something, input_, output):
            #if len(input_) != 1:  # we seem to always get a 1-element tuple here
            #    print(name, len(input_), module)
            #input_ = input_[0]

            if isinstance(input_, tuple) or isinstance(input_, list):
                for i, inp in enumerate(input_):
                    self.log_tensor_stats(inp, f'{input_name}.{i}')
            else:
                self.log_tensor_stats(input_, input_name)

            if isinstance(output, tuple) or isinstance(output, list):
                for i, out in enumerate(output):
                    self.log_tensor_stats(out, f'{output_name}.{i}')
            else:
                self.log_tensor_stats(output, output_name)

            #self.unhook(hook_name)

        handle = module.register_forward_hook(_hook)
        self._hook_handles[hook_name] = handle
        return handle
        #return HOOKS.register(name, lambda: self.log_tensor_stats(grad.data, name))

    def _hook_module_input_output_gradient_stats(self, module, name):
        if not isinstance(module, torch.nn.Module):
            cls = type(module)
            raise TypeError('Expected torch.nn.Module, not {}.{}'.format(
                cls.__module__, cls.__name__))

        hook_name = name + ':io:grad'

        handle = self._hook_handles.get(hook_name)
        if handle is not None and _torch_hook_handle_is_valid(handle):
            raise ValueError(
                'A hook has already been set under name "{}"'.format(hook_name))

        def _hook(something, input_, output):
            #if len(input_) != 1:  # we seem to always get a 1-element tuple here
            #    print(name, len(input_), module)
            #input_ = input_[0]

            if isinstance(input_, tuple) or isinstance(input_, list):
                for i, inp in enumerate(input_):
                    self.log_tensor_stats(inp, f'{name}:input.{i}:grad')
            else:
                self.log_tensor_stats(input_, f'{name}:input:grad')

            if isinstance(output, tuple) or isinstance(output, list):
                for i, out in enumerate(output):
                    self.log_tensor_stats(out, f'{name}.{i}:grad')
            else:
                self.log_tensor_stats(output, f'{name}:output:grad')

        handle = module.register_forward_hook(_hook)
        self._hook_handles[hook_name] = handle
        return handle
        #return HOOKS.register(name, lambda: self.log_tensor_stats(grad.data, name))

    def _hook_variable_gradient_stats(self, var, name):
        """Logs a Variable's gradient's distribution statistics next time backward()
        is called on it.
        """
        if not isinstance(var, torch.autograd.Variable):
            cls = type(var)
            raise TypeError('Expected torch.Variable, not {}.{}'.format(
                cls.__module__, cls.__name__))

        handle = self._hook_handles.get(name)
        if handle is not None and _torch_hook_handle_is_valid(handle):
            raise ValueError(
                'A hook has already been set under name "{}"'.format(name))

        def _callback(grad):
            #_callback()
            self.log_tensor_stats(grad.data, name)
            #self.unhook(name)

        handle = var.register_hook(_callback)
        self._hook_handles[name] = handle
        return handle
        #return HOOKS.register(name, lambda: self.log_tensor_stats(grad.data, name))

    def unhook(self, name):
        handle = self._hook_handles.pop(name)
        handle.remove()


class TorchHooks(object):
    def __init__(self):
        self._hook_handles = {}


    def hook(name, callback):
        pass


def _torch_hook_handle_is_valid(handle):
    d = handle.hooks_dict_ref()
    if d is None:
        return False
    else:
        return handle.id in d
