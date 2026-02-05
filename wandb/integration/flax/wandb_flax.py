"""JAX/Flax-specific functionality."""

from typing import TYPE_CHECKING, Any, Callable, List

import wandb
from wandb import util

jax = None
flax_linen = None

if TYPE_CHECKING:
    pass

# Global storage for captured gradients and params
_captured_grads = None
_captured_params = None

LOG_TRACK_COUNT, LOG_TRACK_THRESHOLD = range(2)


def log_track_init(log_freq: int) -> List[int]:
    """Create tracking structure used by log_track_update."""
    log_track = [0, 0]
    log_track[LOG_TRACK_THRESHOLD] = log_freq
    return log_track


def log_track_update(log_track: List[int]) -> bool:
    """Count (log_track[0]) up to threshold (log_track[1]), reset count (log_track[0]) and return true when reached."""
    log_track[LOG_TRACK_COUNT] += 1
    if log_track[LOG_TRACK_COUNT] < log_track[LOG_TRACK_THRESHOLD]:
        return False
    log_track[LOG_TRACK_COUNT] = 0
    return True


def _compute_histogram_from_numpy(array_np: Any, num_bins: int = 64) -> tuple:
    """Compute histogram from numpy array.

    Returns:
        tuple of (histogram_values, bin_edges) compatible with wandb.Histogram
    """
    np = util.get_module("numpy", required="Histogram computation requires NumPy")

    # Remove NaN and Inf values
    array_np = array_np[np.isfinite(array_np)]

    if len(array_np) == 0:
        return None

    # Flatten the array
    flat = array_np.flatten()

    # Compute min/max
    tmin = float(np.min(flat))
    tmax = float(np.max(flat))

    # Handle edge case where all values are equal
    if tmin == tmax:
        return ([len(flat)], [tmin, tmax])

    # Compute histogram
    histogram, bins = np.histogram(flat, bins=num_bins, range=(tmin, tmax))

    return (histogram.tolist(), bins.tolist())


class FlaxHistory:
    """History methods specific to JAX/Flax."""

    def __init__(self):
        global jax, flax_linen
        jax = wandb.util.get_module("jax", "Could not import jax")
        try:
            import flax.linen as linen

            flax_linen = linen
        except ImportError:
            flax_linen = None

        self._num_bins = 64
        self._watched_model = None
        self._watched_model_id = None
        self._log_type = None
        self._log_params_track = None
        self._log_grads_track = None
        self._original_grad = None
        self._original_value_and_grad = None
        self._hooks_installed = False

    def watch(
        self,
        model: Any,
        log: str = "gradients",
        log_freq: int = 1000,
    ) -> None:
        """Configure watching for a Flax model.

        Args:
            model: Flax module to watch
            log: One of "gradients", "parameters", or "all"
            log_freq: Frequency (in steps) to log histograms
        """
        # Check if this exact model instance has already been watched
        model_id = id(model)
        if self._watched_model_id == model_id:
            raise ValueError(
                "You can only call `wandb.watch` once per model. Pass a new instance of the model if you need to call wandb.watch again in your code."
            )

        if self._watched_model is not None:
            wandb.termwarn(
                "A different Flax model is already being watched. Overwriting previous watch configuration."
            )

        self._watched_model = model
        self._watched_model_id = model_id
        self._log_type = log

        if log in ["parameters", "all"]:
            self._log_params_track = log_track_init(log_freq)

        if log in ["gradients", "all"]:
            self._log_grads_track = log_track_init(log_freq)

        # Install JAX hooks
        self._install_jax_hooks()

    def _install_jax_hooks(self) -> None:
        """Install hooks into JAX gradient functions."""
        if self._hooks_installed:
            return

        global jax
        if jax is None:
            jax = wandb.util.get_module("jax", "Could not import jax")

        # Store original functions
        self._original_grad = jax.grad
        self._original_value_and_grad = jax.value_and_grad

        # Replace with wrapped versions
        def wrapped_grad(fun: Callable, *args, **kwargs) -> Callable:
            original_grad_fn = self._original_grad(fun, *args, **kwargs)

            def grad_fn(params, *fn_args, **fn_kwargs):
                grads = original_grad_fn(params, *fn_args, **fn_kwargs)
                # Capture for logging
                global _captured_grads, _captured_params
                _captured_grads = grads
                _captured_params = params
                return grads

            return grad_fn

        def wrapped_value_and_grad(fun: Callable, *args, **kwargs) -> Callable:
            original_vg_fn = self._original_value_and_grad(fun, *args, **kwargs)

            def value_and_grad_fn(params, *fn_args, **fn_kwargs):
                value, grads = original_vg_fn(params, *fn_args, **fn_kwargs)
                # Capture for logging
                global _captured_grads, _captured_params
                _captured_grads = grads
                _captured_params = params
                return value, grads

            return value_and_grad_fn

        # Monkey-patch JAX
        jax.grad = wrapped_grad
        jax.value_and_grad = wrapped_value_and_grad

        self._hooks_installed = True

    def unhook_all(self) -> None:
        """Remove JAX hooks and restore original functions."""
        if not self._hooks_installed:
            return

        global jax
        if self._original_grad is not None:
            jax.grad = self._original_grad
        if self._original_value_and_grad is not None:
            jax.value_and_grad = self._original_value_and_grad

        self._hooks_installed = False
        self._original_grad = None
        self._original_value_and_grad = None

    def log_captured(self) -> None:
        """Log captured parameters and gradients."""
        global _captured_grads, _captured_params

        if _captured_params is not None and self._log_params_track is not None:
            if log_track_update(self._log_params_track):
                self._log_pytree_histograms(_captured_params, "parameters")

        if _captured_grads is not None and self._log_grads_track is not None:
            if log_track_update(self._log_grads_track):
                self._log_pytree_histograms(_captured_grads, "gradients")

        # Clear captured data
        _captured_grads = None
        _captured_params = None

    def log_params(
        self,
        params: Any,
        prefix: str = "parameters",
    ) -> None:
        """Log parameter histograms.

        Args:
            params: Parameter pytree (typically state.params)
            prefix: Prefix for logged histogram names
        """
        if self._log_params_track is None:
            return

        if not log_track_update(self._log_params_track):
            return

        self._log_pytree_histograms(params, prefix)

    def log_gradients(
        self,
        grads: Any,
        prefix: str = "gradients",
    ) -> None:
        """Log gradient histograms.

        Args:
            grads: Gradient pytree
            prefix: Prefix for logged histogram names
        """
        if self._log_grads_track is None:
            return

        if not log_track_update(self._log_grads_track):
            return

        self._log_pytree_histograms(grads, prefix)

    def _log_pytree_histograms(
        self,
        pytree: Any,
        prefix: str,
    ) -> None:
        """Log histograms for all arrays in a pytree.

        Args:
            pytree: JAX pytree containing arrays
            prefix: Prefix for histogram names
        """
        if jax is None:
            raise ImportError("JAX is required for Flax integration")

        # Flatten the pytree to get all leaves with their paths
        flat_params, tree_def = jax.tree_util.tree_flatten_with_path(pytree)

        log_dict = {}

        for key_path, param in flat_params:
            # Build a readable name from the key path
            path_parts = []
            for key in key_path:
                if hasattr(key, "key"):
                    # DictKey
                    path_parts.append(str(key.key))
                elif hasattr(key, "idx"):
                    # SequenceKey
                    path_parts.append(str(key.idx))
                else:
                    path_parts.append(str(key))

            param_name = ".".join(path_parts) if path_parts else "param"
            full_name = f"{prefix}/{param_name}"

            # Convert JAX array to numpy on host
            param_np = jax.device_get(param)

            # Compute histogram
            hist_data = _compute_histogram_from_numpy(param_np, self._num_bins)

            if hist_data is not None:
                log_dict[full_name] = wandb.Histogram(np_histogram=hist_data)

        if log_dict:
            wandb.run._log(log_dict, commit=False)

    def unhook(self, name: str) -> None:
        """Remove a specific hook (not used in Flax, kept for API compatibility)."""
        pass

    def unwatch(self) -> None:
        """Stop watching the model and remove hooks."""
        self.unhook_all()
        self._watched_model = None
        self._watched_model_id = None
        self._log_type = None
        self._log_params_track = None
        self._log_grads_track = None
