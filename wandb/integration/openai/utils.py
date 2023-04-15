import functools
import inspect
import logging
import os
import uuid
from contextlib import contextmanager
from typing import Callable

import openai

import wandb
from wandb.integration.openai import gorilla
from wandb.integration.openai.autologging_utils import (
    get_autologging_config,
    _AutologgingSessionManager,
    autologging_is_disabled,
    _AUTOLOGGING_GLOBALLY_DISABLED,
    AutologgingEventLogger,
)

_logger = logging.getLogger(__name__)

_AUTOLOGGING_PATCHES = {}


def update_wrapper_extended(wrapper, wrapped):
    """
    Update a `wrapper` function to look like the `wrapped` function. This is an extension of
    `functools.update_wrapper` that applies the docstring *and* signature of `wrapped` to
    `wrapper`, producing a new function.

    :return: A new function with the same implementation as `wrapper` and the same docstring
             & signature as `wrapped`.
    """
    updated_wrapper = functools.update_wrapper(wrapper, wrapped)
    # Assign the signature of the `wrapped` function to the updated wrapper function.
    # Certain frameworks may disallow signature inspection, causing `inspect.signature()` to throw.
    try:
        updated_wrapper.__signature__ = inspect.signature(wrapped)
    except Exception:
        _logger.debug(
            "Failed to restore original signature for wrapper around %s", wrapped
        )
    return updated_wrapper


def _gen_classes_to_patch():
    """Returns a list of classes to patch for OpenAI API autologging."""
    return [openai.Completion, openai.ChatCompletion, openai.Edit]


def _store_patch(autologging_integration, patch):
    """
    Stores a patch for a specified autologging_integration class. Later to be used for being able
    to revert the patch when disabling autologging.

    param autologging_integration: The name of the autologging wandb_sklearn_integration associated with the
                                    patch.
    param patch: The patch to be stored.
    """
    if autologging_integration in _AUTOLOGGING_PATCHES:
        _AUTOLOGGING_PATCHES[autologging_integration].add(patch)
    else:
        _AUTOLOGGING_PATCHES[autologging_integration] = {patch}


def _wrap_patch(destination, name, patch_obj, settings=None):
    """
    Apply a patch.

    param destination: Patch destination
    :param name: Name of the attribute at the destination
    :param patch_obj: Patch object, it should be a function or a property decorated function
                      to be assigned to the patch point {destination}.{name}
    :param settings: Settings for gorilla.Patch
    """
    if settings is None:
        settings = gorilla.Settings(allow_hit=True, store_hit=True)

    patch = gorilla.Patch(destination, name, patch_obj, settings=settings)
    gorilla.apply(patch)
    return patch


def safe_patch(
    autologging_integration,
    destination,
    function_name,
    patch_function,
):
    """
    Patches the specified `function_name` on the specified `destination` class for autologging
    purposes, preceding its implementation with an error-safe copy of the specified patch
    `patch_function` with the following error handling behavior:
        - Exceptions thrown from the underlying / original function
          (`<destination>.<function_name>`) are propagated to the caller.
        - Exceptions thrown from other parts of the patched implementation (`patch_function`)
          are caught and logged as warnings.
    param autologging_integration: The name of the autologging wandb_sklearn_integration associated with the
                                    patch.
    param destination: The Python class on which the patch is being defined.
    param function_name: The name of the function to patch on the specified `destination` class.
    param patch_function: The patched function code to apply. This is either a `PatchFunction`
                           class definition or a function object. If it is a function object, the
                           first argument should be reserved for an `original` method argument
                           representing the underlying / original function. Subsequent arguments
                           should be identical to those of the original function being patched.
    """

    original_fn = gorilla.get_original_attribute(
        destination, function_name, bypass_descriptor_protocol=False
    )
    # Retrieve raw attribute while bypassing the descriptor protocol
    raw_original_obj = gorilla.get_original_attribute(
        destination, function_name, bypass_descriptor_protocol=True
    )
    if original_fn.__func__ != raw_original_obj.__func__:
        raise RuntimeError(f"Unsupported patch on {str(destination)}.{function_name}")

    elif isinstance(original_fn, (property, classmethod)):
        is_property_method = True

        # For property decorated methods (a kind of method delegation), e.g.
        # class A:
        #   @property
        #   def f1(self):
        #     ...
        #     return delegated_f1
        #
        # suppose `a1` is an instance of class `A`,
        # `A.f1.fget` will get the original `def f1(self)` method,
        # and `A.f1.fget(a1)` will be equivalent to `a1.f1()` and
        # its return value will be the `delegated_f1` function.
        # So using the `property.fget` we can construct the (delegated) "original_fn"
        def original(self, *args, **kwargs):
            # the `original_fn.fget` will get the original method decorated by `property`
            # the `original_fn.fget(self)` will get the delegated function returned by the
            # property decorated method.
            bound_delegate_method = original_fn.fget(self)
            return bound_delegate_method(*args, **kwargs)

    else:
        original: Callable = original_fn
        is_property_method = False

    def safe_patch_function(*args, **kwargs):
        """
        A safe wrapper around the specified `patch_function` implementation designed to
        handle exceptions thrown during the execution of `patch_function`. This wrapper
        distinguishes exceptions thrown from the underlying / original function
        (`<destination>.<function_name>`) from exceptions thrown from other parts of
        `patch_function`. This distinction is made by passing an augmented version of the
        underlying / original function to `patch_function` that uses nonlocal state to track
        whether it has been executed and whether it threw an exception.
        Exceptions thrown from the underlying / original function are propagated to the caller,
        while exceptions thrown from other parts of `patch_function` are caught and logged as
        warnings.
        """
        is_silent_mode = get_autologging_config(
            autologging_integration, "silent", False
        )

        # Whether to exclude auto-logged content from user-created wandb runs
        # (i.e. runs created manually via `wandb.init`)
        exclusive = get_autologging_config(autologging_integration, "exclusive", False)
        user_created_wandb_run_is_active = (
            wandb.run is not None and not _AutologgingSessionManager.active_session()
        )
        active_session_failed = (
            _AutologgingSessionManager.active_session() is not None
            and _AutologgingSessionManager.active_session().state == "failed"
        )

        if (
            active_session_failed
            or autologging_is_disabled(autologging_integration)
            or (user_created_wandb_run_is_active and exclusive)
            or _AUTOLOGGING_GLOBALLY_DISABLED
        ):
            return original(*args, **kwargs)

        # Whether the original / underlying function has been called during the
        # execution of patched code
        original_has_been_called = False
        # The value returned by the call to the original / underlying function during
        # the execution of patched code
        original_result = None
        # Whether an exception was raised from within the original / underlying function
        # during the execution of patched code
        failed_during_original = False
        # The active wandb run (if any) associated with patch code execution
        patch_function_run_for_testing = None
        # The exception raised during executing patching function
        patch_function_exception = None

        def try_log_autologging_event(log_fn, *args):
            try:
                log_fn(*args)
            except Exception as e:
                _logger.debug(
                    "Failed to log autologging event via '%s'. Exception: %s",
                    log_fn,
                    e,
                )

        def call_original_fn_with_event_logging(original_fn, og_args, og_kwargs):
            try:
                try_log_autologging_event(
                    AutologgingEventLogger.get_logger().log_original_function_start,
                    session,
                    destination,
                    function_name,
                    og_args,
                    og_kwargs,
                )
                original_fn_result = original_fn(*og_args, **og_kwargs)

                try_log_autologging_event(
                    AutologgingEventLogger.get_logger().log_original_function_success,
                    session,
                    destination,
                    function_name,
                    og_args,
                    og_kwargs,
                )
                return original_fn_result
            except Exception as original_fn_e:
                try_log_autologging_event(
                    AutologgingEventLogger.get_logger().log_original_function_error,
                    session,
                    destination,
                    function_name,
                    og_args,
                    og_kwargs,
                    original_fn_e,
                )

                nonlocal failed_during_original
                failed_during_original = True
                raise

        with _AutologgingSessionManager.start_session(
            autologging_integration
        ) as session:
            try:

                def call_original(*og_args, **og_kwargs):
                    def _original_fn(*_og_args, **_og_kwargs):
                        nonlocal original_has_been_called
                        original_has_been_called = True

                        nonlocal original_result

                        original_result = original(*_og_args, **_og_kwargs)
                        return original_result

                    return call_original_fn_with_event_logging(
                        _original_fn, og_args, og_kwargs
                    )

                # Apply the name, docstring, and signature of `original` to `call_original`.
                # This is important because several autologging patch implementations inspect
                # the signature of the `original` argument during execution
                call_original = update_wrapper_extended(call_original, original)

                try_log_autologging_event(
                    AutologgingEventLogger.get_logger().log_patch_function_start,
                    session,
                    destination,
                    function_name,
                    args,
                    kwargs,
                )

                patch_function(call_original, *args, **kwargs)

                session.state = "succeeded"

                try_log_autologging_event(
                    AutologgingEventLogger.get_logger().log_patch_function_success,
                    session,
                    destination,
                    function_name,
                    args,
                    kwargs,
                )
            except Exception as e:
                session.state = "failed"
                patch_function_exception = e
                # Exceptions thrown during execution of the original function should be
                # propagated to the caller. Additionally, exceptions encountered during test
                # mode should be reraised to detect bugs in autologging implementations
                if failed_during_original:  # or is_testing():
                    raise

            try:
                if original_has_been_called:
                    return original_result
                else:
                    return call_original_fn_with_event_logging(original, args, kwargs)
            finally:
                # If original function succeeds, but `patch_function_exception` exists,
                # it represents patching code unexpected failure, so we call
                # `log_patch_function_error` in this case.
                # If original function failed, we don't call `log_patch_function_error`
                # even if `patch_function_exception` exists, because original function failure
                # means there's some error in user code (e.g. user provide wrong arguments)
                if patch_function_exception is not None and not failed_during_original:
                    try_log_autologging_event(
                        AutologgingEventLogger.get_logger().log_patch_function_error,
                        session,
                        destination,
                        function_name,
                        args,
                        kwargs,
                        patch_function_exception,
                    )

                    _logger.warning(
                        "Encountered unexpected error during %s autologging: %s",
                        autologging_integration,
                        patch_function_exception,
                    )

    if is_property_method:
        # Create a patched function (also property decorated)
        # like:
        #
        # class A:
        # @property
        # def get_bound_safe_patch_fn(self):
        #   original_fn.fget(self) # do availability check
        #   return bound_safe_patch_fn
        #
        # Suppose `a1` is instance of class A,
        # then `a1.get_bound_safe_patch_fn(*args, **kwargs)` will be equivalent to
        # `bound_safe_patch_fn(*args, **kwargs)`
        def get_bound_safe_patch_fn(self):
            # This `original_fn.fget` call is for availability check, if it raises error
            # then `hasattr(obj, {func_name})` will return False,
            # so it mimic the original property behavior.
            original_fn.fget(self)

            def bound_safe_patch_fn(*args, **kwargs):
                return safe_patch_function(self, *args, **kwargs)

            # Make bound method `instance.target_method` keep the same doc and signature
            bound_safe_patch_fn = update_wrapper_extended(
                bound_safe_patch_fn, original_fn.fget
            )
            # Here return the bound safe patch function because user call property decorated
            # method will like `instance.property_decorated_method(...)`, and internally it will
            # call the `bound_safe_patch_fn`, the argument list don't include the `self` argument,
            # so return bound function here.
            return bound_safe_patch_fn

        # Make unbound method `class.target_method` keep the same doc and signature
        get_bound_safe_patch_fn = update_wrapper_extended(
            get_bound_safe_patch_fn, original_fn.fget
        )
        safe_patch_obj = property(get_bound_safe_patch_fn)
    else:
        safe_patch_obj = update_wrapper_extended(safe_patch_function, original)

    new_patch = _wrap_patch(destination, function_name, safe_patch_obj)
    _store_patch(autologging_integration, new_patch)


def _patch_method_if_available(flavour_name, class_def, func_name, patched_fn):
    if not hasattr(class_def, func_name):
        # method not available. skip patching
        return

    original = gorilla.get_original_attribute(
        class_def, func_name, bypass_descriptor_protocol=False
    )
    # Retrieve raw attribute while bypassing the descriptor protocol
    raw_original_obj = gorilla.get_original_attribute(
        class_def, func_name, bypass_descriptor_protocol=True
    )

    if raw_original_obj.__func__ == original.__func__ and (
        callable(original) or isinstance(original, property)
    ):
        # normal method or property decorated method
        safe_patch(
            flavour_name,
            class_def,
            func_name,
            patched_fn,
        )
    elif hasattr(raw_original_obj, "delegate_names") or hasattr(
        raw_original_obj, "check"
    ):
        safe_patch(
            flavour_name,
            raw_original_obj,
            "fn",
            patched_fn,
        )
    else:
        # unsupported method type. skip patching
        pass
