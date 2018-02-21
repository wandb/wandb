import weakref
import wandb
torch = None


class TorchHistory(object):
    """History methods specific to PyTorch
    """

    def __init__(self, history):
        global torch
        import torch
        self._history = weakref.ref(history)
        self._hook_handles = {}

    def log_stats(self, variable_or_module, name=None, prefix='_', values=True, gradients=True):
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
            for name, parameter in module.named_parameters():
                self.log_stats(parameter, name=name, prefix=prefix,
                               values=values, gradients=gradients)
        else:
            cls = type(var)
            raise TypeError('Expected torch.autograd.Variable or torch.nn.Module, not {}.{}'.format(
                cls.__module__, cls.__name__))

    def log_tensor_stats(self, tensor, name):
        """Add distribution statistics on a tensor's elements to the current History entry
        """
        if not hasattr(tensor, 'shape'):  # checking for inheritance from _TensorBase didn't work for some reason
            cls = type(tensor)
            raise TypeError('Expected Tensor, not {}.{}'.format(
                cls.__module__, cls.__name__))
        history = self._history()
        if history is None or not history.compute:
            return
        flat = tensor.view(-1)
        l = len(flat)
        # kthvalue uses 1-based indexing for some reason
        i0_05 = max(1, min(int(round(0.05 * l)), l))
        i0_95 = max(1, min(int(round(0.95 * l)), l))
        history.row.update({
            name + '-0.00': tensor.min(),
            name + '-0.05': flat.kthvalue(i0_05)[0][0],
            name + '-0.50': tensor.median(),
            name + '-0.95': flat.kthvalue(i0_95)[0][0],
            name + '-1.00': tensor.max(),
            name + '-mean': tensor.mean(),
            name + '-stddev': tensor.std()
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
        if handle is not None and _torch_hook_handle_is_valid(handle):
            raise ValueError(
                'A hook has already been set under name "{}"'.format(name))

        def callback(grad):
            self.log_tensor_stats(grad.data, name)
            self.unhook(name)

        handle = var.register_hook(callback)
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
