import pytest

pytest.importorskip("jax")
pytest.importorskip("flax")

import jax
import jax.numpy as jnp
import optax
from flax import linen as nn
from flax.training import train_state
from wandb.integration.flax import wandb_flax


class SimpleModel(nn.Module):
    """Simple Flax model for testing."""

    @nn.compact
    def __call__(self, x):
        x = nn.Dense(features=10)(x)
        return x


def test_log_track_init():
    """Test log tracking initialization."""
    log_track = wandb_flax.log_track_init(log_freq=100)
    assert log_track[wandb_flax.LOG_TRACK_COUNT] == 0
    assert log_track[wandb_flax.LOG_TRACK_THRESHOLD] == 100


def test_log_track_update():
    """Test log tracking update mechanism."""
    log_track = wandb_flax.log_track_init(log_freq=3)

    # First two calls should return False
    assert wandb_flax.log_track_update(log_track) is False
    assert log_track[wandb_flax.LOG_TRACK_COUNT] == 1

    assert wandb_flax.log_track_update(log_track) is False
    assert log_track[wandb_flax.LOG_TRACK_COUNT] == 2

    # Third call should return True and reset
    assert wandb_flax.log_track_update(log_track) is True
    assert log_track[wandb_flax.LOG_TRACK_COUNT] == 0

    # Cycle repeats
    assert wandb_flax.log_track_update(log_track) is False
    assert log_track[wandb_flax.LOG_TRACK_COUNT] == 1


@pytest.mark.parametrize(
    "test_input,should_be_none",
    [
        (jnp.array([1.0, 2.0, 3.0]), False),
        (jnp.array([1.0]), False),
        (jnp.array([1.0, 1.0, 1.0]), False),
        (jnp.array([]), True),
        (jnp.array([float("nan"), float("nan")]), True),
        (jnp.array([float("inf"), float("inf")]), True),
    ],
)
def test_compute_histogram_from_numpy(test_input, should_be_none):
    """Test histogram computation from JAX arrays."""
    result = wandb_flax._compute_histogram_from_numpy(test_input)

    if should_be_none:
        assert result is None
    else:
        assert result is not None
        hist, bins = result
        # Check structure
        assert isinstance(hist, list)
        assert isinstance(bins, list)
        # bins should have one more element than hist
        assert len(bins) == len(hist) + 1
        # Total count should match input size
        assert sum(hist) == len(test_input)


def test_compute_histogram_from_numpy_with_range():
    """Test histogram computation with varied values."""
    test_input = jnp.array([1.0, 2.0, 3.0, 4.0, 5.0])
    result = wandb_flax._compute_histogram_from_numpy(test_input, num_bins=5)

    assert result is not None
    hist, bins = result
    assert len(hist) == 5
    assert len(bins) == 6  # num_bins + 1
    assert sum(hist) == 5  # Total count


def test_compute_histogram_filters_nan_inf():
    """Test that NaN and Inf values are filtered out."""
    test_input = jnp.array([1.0, 2.0, float("nan"), 3.0, float("inf"), 4.0])
    result = wandb_flax._compute_histogram_from_numpy(test_input)

    assert result is not None
    hist, _ = result
    # Should only count the 4 finite values
    assert sum(hist) == 4


def test_double_watch(mock_run):
    """Test that watching the same Flax model twice raises an error."""
    run = mock_run()
    model = SimpleModel()
    run.watch(model)
    with pytest.raises(
        ValueError,
        match="You can only call `wandb.watch` once per model",
    ):
        run.watch(model)


def test_watch_different_models(mock_run):
    """Test that watching different Flax model instances works."""
    run = mock_run()
    model1 = SimpleModel()
    model2 = SimpleModel()

    # Should not raise
    run.watch(model1)
    run.watch(model2)


def test_watch_bad_argument(mock_run):
    """Test that invalid log argument raises ValueError."""
    run = mock_run(use_magic_mock=True)
    model = SimpleModel()
    with pytest.raises(
        ValueError,
        match="log must be one of 'gradients', 'parameters', 'all', or None",
    ):
        run.watch(model, log="bad_argument")


def test_watch_log_graph_warning(mock_run, mock_wandb_log):
    """Test that log_graph=True with Flax shows a warning."""
    run = mock_run(use_magic_mock=True)
    model = SimpleModel()
    run.watch(model, log_graph=True)

    mock_wandb_log.assert_warned("log_graph is not supported for Flax models")


def test_watch_multiple_models_warning(mock_run, mock_wandb_log):
    """Test that watching multiple Flax models shows a warning."""
    run = mock_run(use_magic_mock=True)
    model1 = SimpleModel()
    model2 = SimpleModel()

    run.watch([model1, model2])

    mock_wandb_log.assert_warned("Only the first model will be watched")


@pytest.mark.parametrize("log_type", ["gradients", "parameters", "all"])
def test_watch_hooks_installed(mock_run, log_type):
    """Test that JAX hooks are installed when watching a Flax model."""
    run = mock_run()
    model = SimpleModel()

    # Watch should install hooks
    run.watch(model, log=log_type)

    # Check that hooks were installed
    assert run._flax._hooks_installed is True

    # Check that original JAX functions were stored
    assert run._flax._original_grad is not None
    assert run._flax._original_value_and_grad is not None


def test_watch_with_none_log(mock_run):
    """Test that log=None disables logging."""
    run = mock_run()
    model = SimpleModel()

    run.watch(model, log=None)

    # Both tracking should be None when log=None
    assert run._flax._log_params_track is None
    assert run._flax._log_grads_track is None


@pytest.mark.parametrize("log_type", ["parameters", "all"])
def test_watch_enables_parameter_tracking(mock_run, log_type):
    """Test that parameter tracking is enabled for appropriate log types."""
    run = mock_run()
    model = SimpleModel()

    run.watch(model, log=log_type, log_freq=50)

    assert run._flax._log_params_track is not None
    assert run._flax._log_params_track[wandb_flax.LOG_TRACK_THRESHOLD] == 50


@pytest.mark.parametrize("log_type", ["gradients", "all"])
def test_watch_enables_gradient_tracking(mock_run, log_type):
    """Test that gradient tracking is enabled for appropriate log types."""
    run = mock_run()
    model = SimpleModel()

    run.watch(model, log=log_type, log_freq=75)

    assert run._flax._log_grads_track is not None
    assert run._flax._log_grads_track[wandb_flax.LOG_TRACK_THRESHOLD] == 75


def test_watch_gradient_capture(mock_run):
    """Test that gradients are captured by JAX hooks."""

    run = mock_run()
    model = SimpleModel()

    # Initialize model
    rng = jax.random.PRNGKey(0)
    params = model.init(rng, jnp.ones([1, 5]))["params"]
    tx = optax.sgd(0.01)
    state = train_state.TrainState.create(apply_fn=model.apply, params=params, tx=tx)

    # Watch model
    run.watch(model, log="all", log_freq=1)

    # Define a simple loss function
    def loss_fn(params, x):
        logits = model.apply({"params": params}, x)
        return jnp.mean(logits**2)

    # This should trigger the hook
    x = jnp.ones([1, 5])
    loss, grads = jax.value_and_grad(loss_fn)(state.params, x)

    # Verify gradients were captured
    from wandb.integration.flax.wandb_flax import _captured_grads, _captured_params

    assert _captured_grads is not None
    assert _captured_params is not None


def test_watch_unhook(mock_run):
    """Test that unhook_all removes JAX hooks."""
    run = mock_run()
    model = SimpleModel()

    # Store original JAX functions
    original_grad = jax.grad
    original_value_and_grad = jax.value_and_grad

    # Watch should install hooks
    run.watch(model)
    assert run._flax._hooks_installed is True

    # JAX functions should be wrapped
    assert jax.grad != original_grad
    assert jax.value_and_grad != original_value_and_grad

    # Unhook should restore original functions
    run._flax.unhook_all()
    assert run._flax._hooks_installed is False
    assert jax.grad == original_grad
    assert jax.value_and_grad == original_value_and_grad


def test_unwatch(mock_run):
    """Test that unwatch removes hooks and clears state."""
    run = mock_run()
    model = SimpleModel()

    # Store original JAX functions
    original_grad = jax.grad
    original_value_and_grad = jax.value_and_grad

    # Watch model
    run.watch(model, log="all", log_freq=100)
    assert run._flax._watched_model is not None
    assert run._flax._hooks_installed is True

    # Unwatch should clear everything
    run.unwatch(model)
    assert run._flax._watched_model is None
    assert run._flax._watched_model_id is None
    assert run._flax._log_params_track is None
    assert run._flax._log_grads_track is None
    assert run._flax._hooks_installed is False

    # JAX functions should be restored
    assert jax.grad == original_grad
    assert jax.value_and_grad == original_value_and_grad


def test_unwatch_all(mock_run):
    """Test that unwatch() with no arguments unwatches everything."""
    run = mock_run()
    model = SimpleModel()

    # Watch model
    run.watch(model, log="all")
    assert run._flax._watched_model is not None
    assert run._flax._hooks_installed is True

    # Unwatch all
    run.unwatch()
    assert run._flax._watched_model is None
    assert run._flax._hooks_installed is False


def test_log_captured_respects_frequency(mock_run):
    """Test that log_captured respects the log frequency."""
    run = mock_run()
    model = SimpleModel()

    # Initialize model
    rng = jax.random.PRNGKey(0)
    params = model.init(rng, jnp.ones([1, 5]))["params"]

    # Watch with frequency of 2
    run.watch(model, log="parameters", log_freq=2)

    # Define a simple loss function
    def loss_fn(params):
        x = jnp.ones([1, 5])
        logits = model.apply({"params": params}, x)
        return jnp.mean(logits**2)

    # First gradient computation
    _ = jax.grad(loss_fn)(params)

    # Manually inject captured params for testing
    import wandb.integration.flax.wandb_flax as flax_module

    flax_module._captured_params = params

    # First call should not log (frequency not reached)
    initial_count = run._flax._log_params_track[wandb_flax.LOG_TRACK_COUNT]
    run._flax.log_captured()
    # Count should have incremented but not logged
    assert run._flax._log_params_track[wandb_flax.LOG_TRACK_COUNT] == initial_count + 1
