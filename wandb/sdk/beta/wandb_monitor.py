#
"""
Monitor inference with Weights & Biases
"""

import atexit
import copy
import functools
import inspect
import sys
import threading
from timeit import default_timer as timer

import wandb
from wandb.data_types import Table

from ..internal import sample
from ..wandb_artifacts import Artifact
from ..wandb_settings import Settings

if wandb.TYPE_CHECKING:
    from typing import (
        NamedTuple,
        Dict,
        Optional,
        Union,
        Callable,
        Tuple,
        TypeVar,
        Any,
    )  # noqa: F401

    T = TypeVar("T")
else:
    # Awful hack for python2
    NamedTuple = object

np = wandb.util.get_module("numpy")


class ArgType(NamedTuple):
    key: Union[str, int]
    source: str
    bytes: int
    data_type: Optional[str]
    shape: Optional[Tuple[int]]
    pass


class Prediction:
    """
    A Prediction represents a call to your predict function.  You will be passed a
    sampled list of `Prediction` objects to the `to_table` function you define.

    Attributes:
        args (tuple): The un-named arguments of the function call
        kwargs (dict): The named arguments of the function call
        results (tuple): The return values of the function call
        millis (optional): The number of milliseconds the call took
    """

    def __init__(
        self,
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
        results: Tuple[Any, ...],
        millis: Optional[int] = None,
    ):
        self.args = args
        self.kwargs = kwargs
        self.results = results
        self.millis = millis

    def to_numpy(
        self, arg_type: ArgType
    ) -> Union[None, Any]:  # TODO: get numpy typings working
        """
        Used internally to find arguments and return values that we can compute
        histograms from.

        Attributes:
            arg_type (ArgType): The datatype detected
        """
        if arg_type.data_type == "df":
            return getattr(self, arg_type.source)[arg_type.key].to_numpy()
        elif arg_type.data_type == "np":
            return getattr(self, arg_type.source)[arg_type.key]
        else:
            return None


class Monitor:
    """
    Monitor is a helper class that keeps track of statistics and periodically
    flushes them to W&B.  It's generally used via the @wandb.beta.monitor decorator
    function, but can also be used directly.

    Attributes:
        func (func, optional): A function to monitor
        to_table (func, optional): A function which returns a `wandb.Table` and accepts a
            sampled list of `Call` objects.
        name_or_artifact (str, Artifact, optional): The name or Artifact instance to store
            the data visualization table.
        max_pred_samples (int, optional): The maximum number of calls to sample an buffer in
            memory
        flush_interval (int, optional): The number of seconds to buffer calls before flushing
            to W&B

    Examples:
        Basic usage
        ```python
        wandb.init(project="monitoring")

        def to_table(preds):
            table = wandb.Table("Input", "Output")
            for pred in preds:
                table.add_data([wandb.Image(pred.args[0]), np.argmax(pred.results[0])])
            return table

        monitor = wandb.beta.Monitor(to_table=to_table)

        def predict(input, id=None):
            monitor.input(input[-5:], id)
            results = model.predict(input)
            monitor.output(results[-5:])
        ```
    """

    # The estimated memory buffer size to warn
    BUFFER_WARNING_BYTES = 1024 * 1024 * 100

    def __init__(
        self,
        func: Optional[Callable[..., Any]] = None,
        to_table: Optional[Callable[[Tuple[Prediction]], Union[Any, Table]]] = None,
        name_or_artifact: Optional[Union[str, Artifact]] = None,
        max_pred_samples: int = 64,
        flush_interval: int = 60 * 5,
        config: Union[Dict, str, None] = None,
        settings: Union[Settings, Dict[str, Any], None] = None,
    ):
        self._func: Callable[..., Any]
        if func is None:
            self._func = lambda *args, **kwargs: ()
        else:
            self._func = func
        self._is_method = (
            inspect.signature(self._func).parameters.get("self") is not None
        )
        self._flush_interval = flush_interval
        self._max_samples = max_pred_samples
        # TODO: actually make this max_samples?
        self._sampled_preds = sample.UniformSampleAccumulator(max_pred_samples // 2)
        self._counter = 0
        self._flush_count = 0
        self._config = config
        self._settings = settings
        # TODO: type the schema
        self._schema: Dict[str, Any] = {}
        self._join_event = threading.Event()
        self._to_table = to_table
        self.disabled = False
        self._last_args: Tuple[Any, ...] = ()
        self._last_kwargs: Dict[str, Any] = {}
        self._last_input: Union[None, float] = None
        if isinstance(name_or_artifact, wandb.Artifact):
            self._artifact = name_or_artifact
        else:
            if name_or_artifact is None:
                name_or_artifact = "monitored"
            self._artifact = wandb.Artifact(name_or_artifact, "inference")
        # TODO: make sure this atexit is triggered before ours...
        atexit.register(lambda: self._join_event.set())
        self._ensure_run()
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True
        self._thread.start()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.disabled:
            return self._func(*args, **kwargs)
        else:
            if self._to_table is None and self._is_method:
                if hasattr(args[0], "to_table"):
                    self._to_table = args[0].to_table
            self.input(*args, **kwargs)
            return self.output(self._func(*args, **kwargs))

    def _thread_body(self) -> None:
        join_requested = False
        while not join_requested:
            join_requested = self._join_event.wait(self._flush_interval)
            # TODO: maybe not flush on exit?
            if not self.disabled:
                self.flush()

    def input(self, *args: Any, **kwargs: Any) -> Any:
        """Record an input, should be followed by a call to .output"""
        self._last_args = tuple(args)
        if self._is_method:
            self._last_args = self._last_args[1:]
        self._last_kwargs = kwargs
        self._last_input = timer()

    def output(self, result: Tuple[T]) -> Union[None, Tuple[T]]:
        """Records a Prediction, you must call .input before calling this method"""
        if self.disabled:
            return None
        if self._last_input is None:
            raise AttributeError("You must call input before calling output")
        end = timer()
        self.prediction(
            result, *self._last_args, millis=end - self._last_input, **self._last_kwargs
        )
        self._last_input = None
        return result

    def prediction(
        self, result: Union[Any, Tuple[Any, ...]], *args: Any, **kwargs: Any
    ) -> None:
        """
        Records a prediction

        Attributes:
            result (tuple): The output of a predict method
            *args: the arguments passed into the predict method
            millis (int): The number of milliseconds it took to make the predcition
            **kwargs: named arguments passed into the predict method
        """
        # Py2 doesn't let me name this parameter as a kwarg :(
        millis = kwargs.get("millis")
        if millis is not None:
            del kwargs["millis"]
        # TODO: potentially make this async, although the overhead should be minimal
        self._counter += 1
        if isinstance(result, tuple):
            results = result
        else:
            results = (result,)

        if self._schema == {}:
            self._detect_schema(results, args, kwargs)

        self._sampled_preds.add(Prediction(args, kwargs, results, millis))

    def flush(self) -> None:
        """
        Flush all sampled metrics to W&B
        """
        preds = self._sampled_preds.get()
        if len(preds) == 0:
            return
        metrics: Dict[str, Any] = {"calls": self._counter}
        self._counter = 0
        self._sampled_preds = sample.UniformSampleAccumulator(self._max_samples)
        for arg in self._schema["inputs"]:
            if arg.data_type in ["df", "np"]:
                metric_name = f"input_{arg.key}"
                # TODO: should we average? np.average(vals, axis=0)
                # TODO: should we try to set max bins inteligently?
                metrics[metric_name] = wandb.Histogram(
                    np.array([p.to_numpy(arg) for p in preds])
                )

        pred_times = [p.millis for p in preds]
        metrics["average_call_time"] = sum(pred_times) / len(pred_times)

        # TODO: multiple outputs?
        if self._schema["outputs"][0].data_type in ["df", "np"]:
            metrics["output"] = wandb.Histogram(
                [p.to_numpy(self._schema["outputs"][0]) for p in preds]
            )

        if self._to_table:
            table = self._to_table(preds)
            if isinstance(table, wandb.Table):
                self._artifact.add(table, "examples")
                name = self._artifact.name
                typ = self._artifact.type
                meta = self._artifact.metadata
                wandb.run.log_artifact(self._artifact)  # type: ignore[attr-defined]
                wandb.run.log({"examples": table})  # type: ignore[attr-defined]
                # Reset our artifact for the next flush
                self._artifact = wandb.Artifact(name, typ, metadata=meta)
            else:
                wandb.termwarn(
                    f"to_table returned an incompatible object: {table}"
                )

        self._flush_count += 1
        self._maybe_rotate_run()
        wandb.log(metrics)

    @property
    def estimated_buffer_bytes(self) -> int:
        return self._call_size_bytes() * self._max_samples

    def disable(self) -> bool:
        self.disabled = True
        return self.disabled

    def enable(self) -> bool:
        self.disabled = False
        return self.disabled

    def _ensure_run(self) -> None:
        if wandb.run is None:
            if not isinstance(self._settings, Settings) and self._settings is not None:
                self._settings = wandb.Settings(**self._settings)
            wandb.init(config=self._config, settings=self._settings)

    def _maybe_rotate_run(self) -> bool:
        # TODO: decide if this is the right metric...
        if self._flush_count > 100000:
            config = dict(wandb.run.config)  # type: ignore[attr-defined]
            settings = copy.copy(wandb.run._settings)  # type: ignore[attr-defined]
            settings.run_id = None
            wandb.finish()
            self._flush_count = 0
            # TODO: verify this is actually enough
            wandb.init(config=config, settings=settings)
            return True
        else:
            return False

    # TODO: make byte size factor into our buffer?
    def _call_size_bytes(self) -> int:
        total = 0
        if self._schema:
            for key in ["inputs", "outputs"]:
                for arg in self._schema[key]:
                    total += arg.bytes
        return total

    def _data_type(self, obj: Any, source: str, key: Union[str, int]) -> ArgType:
        # TODO: if this happens to be a numpy array less than 36 in length we convert
        # to a list...
        obj, _ = wandb.util.json_friendly(obj)
        if wandb.util.is_numpy_array(obj):
            return ArgType(key, source, obj.nbytes, "np", obj.shape)
        elif wandb.util.is_pandas_data_frame(obj):
            return ArgType(key, source, obj.to_numpy().nbytes, "df", obj.shape)
        else:
            return ArgType(key, source, sys.getsizeof(obj), None, None)

    # todo: this args type is unfortunate...
    def _detect_schema(
        self, results: Tuple[Any, ...], args: Tuple[Any, ...], kwargs: Dict[str, Any]
    ) -> None:
        self._schema = {"inputs": []}
        for index, obj in enumerate(args):
            self._schema["inputs"].append(self._data_type(obj, "args", index))
        for key, obj in kwargs.items():
            self._schema["inputs"].append(self._data_type(obj, "kwargs", key))
        self._schema["outputs"] = []
        for index, _ in enumerate(results):
            self._schema["outputs"].append(self._data_type(results, "results", index))
        estimated_bytes = self.estimated_buffer_bytes
        if estimated_bytes > self.BUFFER_WARNING_BYTES:
            wandb.termwarn(
                "@wandb.beta.monitor estimates {} of memory will be consumed.\nConsider reducing max_pred_samples (currently {}) or use monitor.input(...) and monitor.output(...)".format(
                    wandb.util.to_human_size(estimated_bytes), self._max_samples
                )
            )


def monitor(
    to_table: Optional[Callable[[Tuple[Prediction]], Table]] = None,
    name_or_artifact: Optional[Union[str, Artifact]] = None,
    max_pred_samples: int = 64,
    flush_interval: int = 60 * 5,
    config: Union[Dict, str, None] = None,
    settings: Union[Settings, Dict[str, Any], None] = None,
) -> Any:
    """
    Function or class decorator for performantely monitoring predictions during inference.
    Decorated classes must have a `predict` method.  By default we sample calls to the
    decorated function or `predict` method and log a histogram of inputs and outputs
    every 5 minutes.  We also capture system utilization, call time, and number of calls.

    If you define `to_table` on your class or pass it into @wandb.beta.monitor, we'll call this
    method every flush_interval seconds passing in a sampled list of Predictions.  You can
    access `.args`, `.kwargs`, and `.results` on each prediction and construct an instance
    of wandb.Table to visualize real world predictions.

    Attributes:
        to_table (func): A function which returns a `wandb.Table` and accepts a
            sampled list of `Call` objects.
        name_or_artifact (str, Artifact): The name or Artifact instance to store
            the data visualization table.
        max_pred_samples (int): The maximum number of calls to sample an buffer in
            memory
        flush_interval (int): The number of seconds to buffer calls before flushing
            to W&B
        config (dict):  Sets the config parameters for the run
        settings (dict, wandb.Settings):  A wandb.Settings object or dictionary to configure the run

    Examples:
        Basic usage
        ```python
        wandb.init(project="monitoring")

        def to_table(preds):
            table = wandb.Table("Input", "Output")
            for pred in preds:
                table.add_data([wandb.Image(call.args[0]), np.argmax(call.results[0])])
            return table

        @wandb.beta.monitor(to_table=to_table)
        def predict(input):
            return model.predict(input)
        ```

        Advanced usage
        ```python
        @wandb.beta.monitor(max_pred_samples=32, flush_interval=10, settings={"project": "monitoring"})
        class Model(object):
            def predict(self, input, id=None):
                return self.model.predict(input)

            def to_table(self, preds):
                table = wandb.Table("ID", Input", "Output")
                for pred in preds:
                    table.add_data([call.kwargs["id"], wandb.Image(call.args[0]), np.argmax(call.results[0])])
                return table

        model = Model()

        # disable all monitoring
        model.wandb_monitor.disable()
        # enable all monitoring
        model.wandb_monitor.enable()
        # manually flush captured predictions
        model.wandb_monitor.flush()

    Raises:
        AttributeError - If numpy isn't available or the decorated class doesn't have a
            predict method.

    Returns:
        A wrapped function or class with a wandb_monitor attribute that has the following methods
            flush: manually flush the current call samples
            disable: disable wandb monitoring
            enable: enable wandb monitoring
    """

    def decorator(func: Optional[Callable[..., Any]] = None) -> Any:
        if np is None:
            raise AttributeError("@wandb.beta.monitor requires numpy")
        if sys.version_info.major == 2:
            raise AttributeError("@wandb.beta.monitor requires Python 3.x")

        if func is None:
            raise TypeError("@wandb.beta.monitor must decorate a function or a class")

        # If someone decorates a class, let's ensure it has a predict func
        cls = None
        if inspect.isclass(func):
            cls = func
            if not hasattr(cls, "predict"):
                raise AttributeError(
                    "@wandb.beta.monitor can only decorate classes with a predict method"
                )

        monitor = Monitor(
            func,
            to_table,
            name_or_artifact,
            max_pred_samples,
            flush_interval,
            config,
            settings,
        )

        @functools.wraps(cls or func)
        def wrapper(*args, **kwargs):  # type: ignore
            if cls is not None:
                instance = cls(*args, **kwargs)
                if hasattr(instance, "to_table"):
                    monitor._to_table = instance.to_table
                monitor._func = instance.predict
                instance.predict = functools.update_wrapper(monitor, instance.predict)
                instance.wandb_monitor = monitor
                return instance
            else:
                return monitor(*args, **kwargs)

        wrapper.wandb_monitor = monitor  # type: ignore
        return wrapper

    return decorator
