import atexit
import collections
import copy
from functools import wraps
import sys
import threading
from timeit import default_timer as timer

import wandb
from wandb.data_types import Table
from wandb.sdk.internal import sample
from wandb.sdk.wandb_artifacts import Artifact

if wandb.TYPE_CHECKING:  # type: ignore
    from typing import Optional, Union, Callable  # noqa: F401

np = wandb.util.get_module("numpy")
ArgType = collections.namedtuple(
    "Arg", ("key", "source", "data_type", "shape", "bytes")
)


def human_size(bytes, units=None):
    units = units or ["", "KB", "MB", "GB", "TB", "PB", "EB"]
    return str(bytes) + units[0] if bytes < 1024 else human_size(bytes >> 10, units[1:])


class Call(object):
    """
    A call represents a call to your predict function.  You will be passed a
    sampled list of `Call` objects to the `to_table` function you definie.

    Attributes:
        results: The return values of the function call
        time: The number of milliseconds the call took
        args: The un-named arguments of the function call
        kwargs: The named arguments of the function call
    """

    def __init__(self, results, time, args, kwargs):
        self.results = results
        self.time = time
        self.args = args
        self.kwargs = kwargs

    def to_numpy(self, arg_type):
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


class Monitor(object):
    """
    Monitor is a function decorator class that keeps track of statistics and
    periodically flushes these statistics to W&B.  It's generally used via the
    @wandb.monitor decorator function, see that function for more documentation.
    """

    # The estimated memory buffer size to warn
    BUFFER_WARNING_BYTES = 1024 * 1024 * 100

    def __init__(
        self,
        func,
        artifact_or_name=None,
        max_call_samples=32,
        flush_interval=60,
        to_table=None,
    ):
        self._func = func
        self._flush_interval = flush_interval
        self._max_samples = max_call_samples
        # TODO: actually make this max_samples?
        self._sampled_calls = sample.UniformSampleAccumulator(max_call_samples // 2)
        self._counter = 0
        self._flush_count = 0
        self._schema = None
        self._join_event = threading.Event()
        self._to_table = to_table
        self.disabled = False
        if isinstance(artifact_or_name, wandb.Artifact):
            self._artifact = artifact_or_name
        else:
            if artifact_or_name is None:
                artifact_or_name = "monitored"
            self._artifact = wandb.Artifact(artifact_or_name, "inference")
        # TODO: make sure this atexit is triggered before ours...
        atexit.register(lambda: self._join_event.set())
        self._thread = threading.Thread(target=self._thread_body)
        self._thread.daemon = True
        self._thread.start()

    def disable(self):
        self.disabled = True

    def enable(self):
        self.disabled = False

    def __call__(self, *args, **kwargs):
        if self.disabled:
            return self._func(*args, **kwargs)
        else:
            start = timer()
            result = self._func(*args, **kwargs)
            end = timer()
            # TODO: potentially make this async
            self._process(result, end - start, args, kwargs)
            return result

    def _thread_body(self):
        join_requested = False
        while not join_requested:
            join_requested = self._join_event.wait(self._flush_interval)
            # TODO: maybe not flush on exit?
            if not self.disabled:
                self.flush()

    def _process(self, result, time, args, kwargs):
        self._counter += 1
        if self._schema is None:
            self._detect_schema(result, args, kwargs)

        if isinstance(result, tuple):
            results = result
        else:
            results = (result,)

        self._sampled_calls.add(Call(results, time, args, kwargs))

    def _maybe_rotate_run(self):
        # TODO: decide if this is the right metric...
        if self._flush_count > 100000:
            config = dict(wandb.run.config)
            settings = copy.copy(wandb.run._settings)
            settings.run_id = None
            wandb.finish()
            # TODO: verify this is actually enough
            wandb.init(config=config, settings=settings)

    def flush(self):
        """
        Flush all sampled metrics to W&B
        """
        calls = self._sampled_calls.get()
        if len(calls) == 0:
            return
        metrics = {"calls": self._counter}
        self._counter = 0
        self._sampled_calls = sample.UniformSampleAccumulator(self._max_samples)
        for arg in self._schema["inputs"]:
            if arg.data_type in ["df", "np"]:
                metric_name = "input_{}".format(arg.key)
                # TODO: should we average? np.average(vals, axis=0)
                # TODO: should we try to set max bins inteligently?
                metrics[metric_name] = wandb.Histogram(
                    np.array([c.to_numpy(arg) for c in calls])
                )

        call_times = [c.time for c in calls]
        metrics["average_call_time"] = sum(call_times) / len(call_times)

        # TODO: multiple outputs?
        if self._schema["outputs"][0].data_type in ["df", "np"]:
            metrics["output"] = wandb.Histogram(
                [c.to_numpy(self._schema["outputs"][0]) for c in calls]
            )

        if self._to_table:
            table = self._to_table(calls)
            if isinstance(table, wandb.Table):
                self._artifact.add(table, "examples")
                wandb.run.log_artifact(self._artifact)
                self._artifact = wandb.Artifact(
                    self._artifact.name,
                    self._artifact.type,
                    metadata=self._artifact.metadata,
                )
            else:
                wandb.termwarn(
                    "to_table returned an incompatible object: {}".format(table)
                )

        self._flush_count += 1
        self._maybe_rotate_run()
        wandb.log(metrics)

    # TODO: make byte size factor into our buffer?
    def _call_size_bytes(self):
        total = 0
        if self._schema:
            for key in ["inputs", "outputs"]:
                for arg in self._schema[key]:
                    total += arg.bytes
        return total

    @property
    def estimated_buffer_bytes(self):
        return self._call_size_bytes() * self._max_samples

    def _data_type(self, obj, source=None, key=None):
        # TODO: handle sequences / tensors
        if wandb.util.is_numpy_array(obj):
            return ArgType(key, source, "np", obj.shape, obj.nbytes)
        elif wandb.util.is_pandas_data_frame(obj):
            return ArgType(key, source, "df", obj.shape, obj.to_numpy().nbytes)
        else:
            return ArgType(key, source, None, None, sys.getsizeof(obj))

    def _detect_schema(self, result, args, kwargs):
        self._schema = {"inputs": []}
        for key, obj in enumerate(args):
            self._schema["inputs"].append(self._data_type(obj, "args", key))
        for key, obj in kwargs.items():
            self._schema["inputs"].append(self._data_type(obj, "kwargs", key))
        self._schema["outputs"] = [self._data_type(result, "results", 0)]
        estimated_bytes = self.estimated_buffer_bytes
        if estimated_bytes > self.BUFFER_WARNING_BYTES:
            wandb.termwarn(
                "@wandb.monitor estimates {} of memory will be consumed.\nConsider reducing max_call_samples (currently {})".format(
                    human_size(estimated_bytes), self._max_samples
                )
            )


def monitor(
    to_table: Optional[Callable[..., Table]] = None,
    name_or_artifact: Optional[Union[str, Artifact]] = None,
    max_call_samples: Optional[int] = 32,
    flush_interval: Optional[int] = 60,
):
    """
    Function decorator for performantely monitoring predictions during inference.
    You must call `wandb.init` before using this decorator.  It also requires that
    numpy is available in your environment.

    Attributes:
        to_table (lambda): A function which returns a `wandb.Table` and accepts a
            sampled list of `Call` objects.
        name_or_artifact (str, Artifact): The name or Artifact instance to store
            the data visualization table.
        max_call_samples (int): The maximum number of calls to sample an buffer in
            memory
        flush_interval (int): The number of seconds to buffer calls before flushing
            to W&B

    Examples:
        Basic usage
        ```python
        wandb.init(project="monitoring")

        def to_table(calls):
            table = wandb.Table("Input", "Output")
            for call in calls:
                table.add_data([wandb.Image(call.args[0]), np.argmax(call.results[0])])
            return table

        @wandb.monitor(to_table=to_table)
        def predict(input):
            return model.predict(input)
        ```

        Advanced usage
        ```python
        wandb.init(project="monitoring")

        @wandb.monitor(max_call_samples=64, flush_interval=10)
        def predict(input, id=None):
            return model.predict(input)

        # disable all monitoring
        predict.disable()
        # enable all monitoring
        predict.enable()
        # manually flush captured calls
        predict.flush()

    Returns:
        A wrapped function with the following methods:
            flush: manually flush the current call samples
            disable: disable wandb monitoring
            enable: enable wandb monitoring
    """

    def decorator(func):
        if np is None:
            raise AttributeError("@wandb.monitor requires numpy")
        # TODO: decide if we want to automatically init / move this into the wrapper?
        if wandb.run is None:
            raise ValueError("Call wandb.init before decorating your predict function")
        monitored = Monitor(
            func, name_or_artifact, max_call_samples, flush_interval, to_table
        )

        @wraps(func)
        def wrapper(*args, **kwargs):
            return monitored(*args, **kwargs)

        wrapper.flush = lambda: monitored.flush()
        wrapper.disable = lambda: monitored.disable()
        wrapper.enable = lambda: monitored.enable()
        return wrapper

    return decorator
