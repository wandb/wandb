import contextlib
import logging
import os
import uuid
import warnings
from contextlib import contextmanager

_logger = logging.getLogger(__name__)

_AUTOLOGGING_GLOBALLY_DISABLED = os.environ.get("_AUTOLOGGING_DISABLED", False)
AUTOLOGGING_INTEGRATIONS = {}


class AutologgingSession:
    def __init__(self, integration, id_):
        self.integration = integration
        self.id = id_
        self.state = "running"


class _AutologgingSessionManager:
    _session = None

    @classmethod
    @contextmanager
    def start_session(cls, integration):
        try:
            prev_session = cls._session
            if prev_session is None:
                session_id = uuid.uuid4().hex
                cls._session = AutologgingSession(integration, session_id)
            yield cls._session
        finally:
            # Only end the session upon termination of the context if we created
            # the session; otherwise, leave the session open for later termination
            # by its creator
            if prev_session is None:
                cls._end_session()

    @classmethod
    def active_session(cls):
        return cls._session

    @classmethod
    def _end_session(cls):
        cls._session = None


def autologging_is_disabled(integration_name):
    """
    Returns a boolean flag of whether the autologging wandb_sklearn_integration is disabled.

    param integration_name: An autologging wandb_sklearn_integration flavor name.
    """
    explicit_disabled = get_autologging_config(integration_name, "disable", False)
    if explicit_disabled:
        return True

    # TODO: Add versioning support here
    # if (
    #     integration_name in FLAVOR_TO_MODULE_NAME_AND_VERSION_INFO_KEY
    #     and not is_flavor_supported_for_associated_package_versions(integration_name)
    # ):
    #     return get_autologging_config(integration_name, "disable_for_unsupported_versions", False)

    return False


@contextlib.contextmanager
def disable_autologging():
    """
    Context manager that temporarily disables autologging globally for all integrations upon
    entry and restores the previous autologging configuration upon exit.
    """
    global _AUTOLOGGING_GLOBALLY_DISABLED
    _AUTOLOGGING_GLOBALLY_DISABLED = True
    yield None
    _AUTOLOGGING_GLOBALLY_DISABLED = False


def get_autologging_config(flavor_name, config_key, default_value=None):
    """
    Returns a desired config value for a specified autologging wandb_sklearn_integration.
    Returns `None` if specified `flavor_name` has no recorded configs.
    If `config_key` is not set on the config object, default value is returned.

    param flavor_name: An autologging wandb_sklearn_integration flavor name.
    param config_key: The key for the desired config value.
    param default_value: The default_value to return
    """
    config = AUTOLOGGING_INTEGRATIONS.get(flavor_name)
    if config is not None:
        return config.get(config_key, default_value)
    else:
        return default_value


def _get_new_training_session_class():
    """
    Returns a session manager class for nested autologging runs.
    """

    # NOTE: The current implementation doesn't guarantee thread-safety, but that's okay for now
    # because:
    # 1. We don't currently have any use cases for allow_children=True.
    # 2. The list append & pop operations are thread-safe, so we will always clear the session stack
    #    once all _TrainingSessions exit.
    class _TrainingSession:
        _session_stack = []

        def __init__(self, clazz, allow_children=True):
            """
            A session manager for nested autologging runs.

            param clazz: A class object that this session originates from.
            param allow_children: If True, allows autologging in child sessions.
                                   If False, disallows autologging in all descendant sessions.
            """
            self.allow_children = allow_children
            self.clazz = clazz
            self._parent = None

        def __enter__(self):
            if len(_TrainingSession._session_stack) > 0:
                self._parent = _TrainingSession._session_stack[-1]
                self.allow_children = (
                    _TrainingSession._session_stack[-1].allow_children
                    and self.allow_children
                )
            _TrainingSession._session_stack.append(self)
            return self

        def __exit__(self, tp, val, traceback):
            _TrainingSession._session_stack.pop()

        def should_log(self):
            """
            Returns True when at least one of the following conditions satisfies:

            1. This session is the root session.
            2. The parent session allows autologging and its class differs from this session's
               class.
            """
            return (self._parent is None) or (
                self._parent.allow_children and self._parent.clazz != self.clazz
            )

        @staticmethod
        def is_active():
            return len(_TrainingSession._session_stack) != 0

    return _TrainingSession


class AutologgingEventLogger:
    """
    Provides instrumentation hooks for important autologging lifecycle events, including:

        - Calls to `wandb.autolog()` APIs
        - Calls to patched APIs with associated termination states
          ("success" and "failure due to error")
        - Calls to original / underlying APIs made by patched function code with
          associated termination states ("success" and "failure due to error")

    Default implementations are included for each of these hooks, which emit corresponding
    DEBUG-level logging statements. Developers can provide their own hook implementations
    by subclassing `AutologgingEventLogger` and calling the static
    `AutologgingEventLogger.set_logger()` method to supply a new event logger instance.

    Callers fetch the configured logger via `AutologgingEventLogger.get_logger()`
    and invoke one or more hooks (e.g., `AutologgingEventLogger.get_logger().log_autolog_called()`).
    """

    _event_logger = None

    @staticmethod
    def get_logger():
        """
        Fetches the configured `AutologgingEventLogger` instance for logging.

        :return: The instance of `AutologgingEventLogger` specified via `set_logger`
                 (if configured) or the default implementation of `AutologgingEventLogger`
                 (if a logger was not configured via `set_logger`).
        """
        return AutologgingEventLogger._event_logger or AutologgingEventLogger()

    @staticmethod
    def set_logger(logger):
        """
        Configures the `AutologgingEventLogger` instance for logging. This instance
        is exposed via `AutologgingEventLogger.get_logger()` and callers use it to invoke
        logging hooks (e.g., AutologgingEventLogger.get_logger().log_autolog_called()).

        :param logger: The instance of `AutologgingEventLogger` to use when invoking logging hooks.
        """
        AutologgingEventLogger._event_logger = logger

    @staticmethod
    def log_autolog_called(integration, call_args, call_kwargs):
        """
        Called when the `autolog()` method for an autologging wandb_sklearn_integration
        is invoked (e.g., when a user invokes `wandb.wandb_sklearn_integration.sklearn.autolog()`)

        param wandb_sklearn_integration: The autologging wandb_sklearn_integration for which `autolog()` was called.
        param call_args: **DEPRECATED** The positional arguments passed to the `autolog()` call.
                          This field is empty ; all arguments are passed in
                          keyword form via `call_kwargs`.
        param call_kwargs: The arguments passed to the `autolog()` call in keyword form.
                            Any positional arguments should also be converted to keyword form
                            and passed via `call_kwargs`.
        """
        if len(call_args) > 0:
            warnings.warn(
                "Received %d positional arguments via `call_args`. `call_args` is"
                " deprecated, and all arguments should be passed"
                " in keyword form via `call_kwargs`." % len(call_args),
                category=DeprecationWarning,
                stacklevel=2,
            )
        _logger.debug(
            "Called autolog() method for %s autologging with args '%s' and kwargs '%s'",
            integration,
            call_args,
            call_kwargs,
        )

    @staticmethod
    def log_patch_function_start(
        session, patch_obj, function_name, call_args, call_kwargs
    ):
        """
        Called upon invocation of a patched API associated with an autologging wandb_sklearn_integration
        (e.g., `sklearn.linear_model.LogisticRegression.fit()`).

        param session: The `AutologgingSession` associated with the patched API call.
        param patch_obj: The object (class, module, etc.) on which the patched API was called.
        param function_name: The name of the patched API that was called.
        param call_args: The positional arguments passed to the patched API call.
        param call_kwargs: The keyword arguments passed to the patched API call.
        """
        _logger.debug(
            "Invoked patched API '%s.%s' for %s autologging with args '%s' and kwargs '%s'",
            patch_obj,
            function_name,
            session.integration,
            call_args,
            call_kwargs,
        )

    @staticmethod
    def log_patch_function_success(
        session, patch_obj, function_name, call_args, call_kwargs
    ):
        """
        Called upon successful termination of a patched API associated with an autologging
        wandb_sklearn_integration (e.g., `sklearn.linear_model.LogisticRegression.fit()`).

        param session: The `AutologgingSession` associated with the patched API call.
        param patch_obj: The object (class, module, etc.) on which the patched API was called.
        param function_name: The name of the patched API that was called.
        param call_args: The positional arguments passed to the patched API call.
        param call_kwargs: The keyword arguments passed to the patched API call.
        """
        _logger.debug(
            "Patched API call '%s.%s' for %s autologging completed successfully. Patched ML"
            " API was called with args '%s' and kwargs '%s'",
            patch_obj,
            function_name,
            session.integration,
            call_args,
            call_kwargs,
        )

    @staticmethod
    def log_patch_function_error(
        session, patch_obj, function_name, call_args, call_kwargs, exception
    ):
        """
        Called when execution of a patched API associated with an autologging wandb_sklearn_integration
        (e.g., `sklearn.linear_model.LogisticRegression.fit()`) terminates with an exception.

        param session: The `AutologgingSession` associated with the patched API call.
        param patch_obj: The object (class, module, etc.) on which the patched API was called.
        param function_name: The name of the patched API that was called.
        param call_args: The positional arguments passed to the patched API call.
        param call_kwargs: The keyword arguments passed to the patched API call.
        param exception: The exception that caused the patched API call to terminate.
        """
        _logger.debug(
            "Patched API call '%s.%s' for %s autologging threw exception. Patched API was"
            " called with args '%s' and kwargs '%s'. Exception: %s",
            patch_obj,
            function_name,
            session.integration,
            call_args,
            call_kwargs,
            exception,
        )

    @staticmethod
    def log_original_function_start(
        session, patch_obj, function_name, call_args, call_kwargs
    ):
        """
        Called during the execution of a patched API associated with an autologging wandb_sklearn_integration
        when the original / underlying API is invoked. For example, this is called when
        a patched implementation of `sklearn.linear_model.LogisticRegression.fit()` invokes
        the original implementation of `sklearn.linear_model.LogisticRegression.fit()`.

        param session: The `AutologgingSession` associated with the patched API call.
        param patch_obj: The object (class, module, etc.) on which the original API was called.
        param function_name: The name of the original API that was called.
        param call_args: The positional arguments passed to the original API call.
        param call_kwargs: The keyword arguments passed to the original API call.
        """
        _logger.debug(
            "Original function invoked during execution of patched API '%s.%s' for %s"
            " autologging. Original function was invoked with args '%s' and kwargs '%s'",
            patch_obj,
            function_name,
            session.integration,
            call_args,
            call_kwargs,
        )

    @staticmethod
    def log_original_function_success(
        session, patch_obj, function_name, call_args, call_kwargs
    ):
        """
        Called during the execution of a patched API associated with an autologging wandb_sklearn_integration
        when the original / underlying API invocation terminates successfully. For example,
        when a patched implementation of `sklearn.linear_model.LogisticRegression.fit()` invokes the
        original / underlying implementation of `LogisticRegression.fit()`, then this function is
        called if the original / underlying implementation successfully completes.

        param session: The `AutologgingSession` associated with the patched API call.
        param patch_obj: The object (class, module, etc.) on which the original API was called.
        param function_name: The name of the original API that was called.
        param call_args: The positional arguments passed to the original API call.
        param call_kwargs: The keyword arguments passed to the original API call.
        """
        _logger.debug(
            "Original function invocation completed successfully during execution of patched API"
            " call '%s.%s' for %s autologging. Original function was invoked with with"
            " args '%s' and kwargs '%s'",
            patch_obj,
            function_name,
            session.integration,
            call_args,
            call_kwargs,
        )

    @staticmethod
    def log_original_function_error(
        session, patch_obj, function_name, call_args, call_kwargs, exception
    ):
        """
        Called during the execution of a patched API associated with an autologging wandb_sklearn_integration
        when the original / underlying API invocation terminates with an error. For example,
        when a patched implementation of `sklearn.linear_model.LogisticRegression.fit()` invokes the
        original / underlying implementation of `LogisticRegression.fit()`, then this function is
        called if the original / underlying implementation terminates with an exception.

        param session: The `AutologgingSession` associated with the patched API call.
        param patch_obj: The object (class, module, etc.) on which the original API was called.
        param function_name: The name of the original API that was called.
        param call_args: The positional arguments passed to the original API call.
        param call_kwargs: The keyword arguments passed to the original API call.
        param exception: The exception that caused the original API call to terminate.
        """
        _logger.debug(
            "Original function invocation threw exception during execution of patched"
            " API call '%s.%s' for %s autologging. Original function was invoked with"
            " args '%s' and kwargs '%s'. Exception: %s",
            patch_obj,
            function_name,
            session.integration,
            call_args,
            call_kwargs,
            exception,
        )
