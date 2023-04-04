"""Implements a post-import hook mechanism.

Styled as per PEP-369. Note that it doesn't cope with modules being reloaded.

Note: This file is based on
https://github.com/GrahamDumpleton/wrapt/blob/1.12.1/src/wrapt/importer.py
and manual backports of later patches up to 1.14.1 in the wrapt repository
(with slight modifications).
"""

import functools
import sys
import threading
from importlib.util import find_spec
from typing import Any, Callable, Dict, Optional


# modified the following import: from .decorators import synchronized
def synchronized(lock: "threading.RLock") -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def new_func(*args: Any, **kwargs: Any) -> Any:
            with lock:
                return func(*args, **kwargs)

        return new_func

    return decorator


# The dictionary registering any post import hooks to be triggered once
# the target module has been imported. Once a module has been imported
# and the hooks fired, the list of hooks recorded against the target
# module will be truncated but the list left in the dictionary. This
# acts as a flag to indicate that the module had already been imported.

_post_import_hooks: Dict = {}
_post_import_hooks_init: bool = False
_post_import_hooks_lock = threading.RLock()

# Register a new post import hook for the target module name. This
# differs from the PEP-369 implementation in that it also allows the
# hook function to be specified as a string consisting of the name of
# the callback in the form 'module:function'. This will result in a
# proxy callback being registered which will defer loading of the
# specified module containing the callback function until required.


def _create_import_hook_from_string(name: str) -> Any:
    def import_hook(module: Any) -> Any:
        module_name, function = name.split(":")
        attrs = function.split(".")
        __import__(module_name)
        callback = sys.modules[module_name]
        for attr in attrs:
            callback = getattr(callback, attr)
        return callback(module)  # type: ignore

    return import_hook


@synchronized(_post_import_hooks_lock)
def register_post_import_hook(hook: Callable, hook_id: str, name: str) -> None:
    # Create a deferred import hook if hook is a string name rather than
    # a callable function.

    if isinstance(hook, (str,)):
        hook = _create_import_hook_from_string(hook)  # type: ignore

    # Automatically install the import hook finder if it has not already
    # been installed.

    global _post_import_hooks_init

    if not _post_import_hooks_init:
        _post_import_hooks_init = True
        sys.meta_path.insert(0, ImportHookFinder())  # type: ignore

    # Determine if any prior registration of a post import hook for
    # the target modules has occurred and act appropriately.

    hooks = _post_import_hooks.get(name)

    if hooks is None:
        # No prior registration of post import hooks for the target
        # module. We need to check whether the module has already been
        # imported. If it has we fire the hook immediately and add an
        # empty list to the registry to indicate that the module has
        # already been imported and hooks have fired. Otherwise add
        # the post import hook to the registry.

        module = sys.modules.get(name)

        if module is not None:
            _post_import_hooks[name] = {}
            if hook:  # type: ignore
                hook(module)

        else:
            _post_import_hooks[name] = {hook_id: hook}

    elif hooks == {}:
        # A prior registration of post import hooks for the target
        # module was done and the hooks already fired. Fire the hook
        # immediately.

        module = sys.modules.get(name)

        if module is not None:
            if hook:  # type: ignore
                hook(module)

    else:
        # A prior registration of port post hooks for the target
        # module was done but the module has not yet been imported.

        _post_import_hooks[name].update({hook_id: hook})


@synchronized(_post_import_hooks_lock)
def unregister_post_import_hook(name: str, hook_id: Optional[str]) -> None:
    # Remove the import hook if it has been registered.
    hooks = _post_import_hooks.get(name)

    if hooks is not None:
        if hook_id is not None:
            hooks.pop(hook_id, None)

            if not hooks:
                del _post_import_hooks[name]
        else:
            del _post_import_hooks[name]


@synchronized(_post_import_hooks_lock)
def unregister_all_post_import_hooks() -> None:
    _post_import_hooks.clear()


# Register post import hooks defined as package entry points.


def _create_import_hook_from_entrypoint(entrypoint: Any) -> Callable:
    def import_hook(module: Any) -> Any:
        __import__(entrypoint.module_name)
        callback = sys.modules[entrypoint.module_name]
        for attr in entrypoint.attrs:
            callback = getattr(callback, attr)
        return callback(module)  # type: ignore

    return import_hook


def discover_post_import_hooks(group: Any) -> None:
    try:
        import pkg_resources
    except ImportError:
        return

    for entrypoint in pkg_resources.iter_entry_points(group=group):
        callback = _create_import_hook_from_entrypoint(entrypoint)
        register_post_import_hook(callback, entrypoint.name)


# Indicate that a module has been loaded. Any post import hooks which
# were registered against the target module will be invoked. If an
# exception is raised in any of the post import hooks, that will cause
# the import of the target module to fail.


@synchronized(_post_import_hooks_lock)
def notify_module_loaded(module: Any) -> None:
    name = getattr(module, "__name__", None)
    hooks = _post_import_hooks.get(name)

    if hooks:
        _post_import_hooks[name] = {}
        for hook in hooks.values():
            if hook:
                hook(module)


# A custom module import finder. This intercepts attempts to import
# modules and watches out for attempts to import target modules of
# interest. When a module of interest is imported, then any post import
# hooks which are registered will be invoked.


class _ImportHookChainedLoader:
    def __init__(self, loader: Any) -> None:
        self.loader = loader

    def load_module(self, fullname: str) -> Any:
        if hasattr(loader, "load_module"):
          self.load_module = self._load_module
        if hasattr(loader, "create_module"):
          self.create_module = self._create_module
        if hasattr(loader, "exec_module"):
          self.exec_module = self._exec_module

    def _load_module(self, fullname):
        module = self.loader.load_module(fullname)
        notify_module_loaded(module)

        return module


    # Python 3.4 introduced create_module() and exec_module() instead of
    # load_module() alone. Splitting the two steps.

    def _create_module(self, spec):
        return self.loader.create_module(spec)

    def _exec_module(self, module):
        self.loader.exec_module(module)
        notify_module_loaded(module)


class ImportHookFinder:
    def __init__(self) -> None:
        self.in_progress: Dict = {}

    @synchronized(_post_import_hooks_lock)
    def find_module(  # type: ignore
        self,
        fullname: str,
        path: Optional[str] = None,
    ) -> Optional["_ImportHookChainedLoader"]:
        # If the module being imported is not one we have registered
        # post import hooks for, we can return immediately. We will
        # take no further part in the importing of this module.

        if fullname not in _post_import_hooks:
            return None

        # When we are interested in a specific module, we will call back
        # into the import system a second time to defer to the import
        # finder that is supposed to handle the importing of the module.
        # We set an in progress flag for the target module so that on
        # the second time through we don't trigger another call back
        # into the import system and cause a infinite loop.

        if fullname in self.in_progress:
            return None

        self.in_progress[fullname] = True

        # Now call back into the import system again.

        try:
            # For Python 3 we need to use find_spec().loader
            # from the importlib.util module. It doesn't actually
            # import the target module and only finds the
            # loader. If a loader is found, we need to return
            # our own loader which will then in turn call the
            # real loader to import the module and invoke the
            # post import hooks.
            loader = getattr(find_spec(fullname), "loader", None)
            if loader and not isinstance(loader, _ImportHookChainedLoader):
                return _ImportHookChainedLoader(loader)

        finally:
            del self.in_progress[fullname]

    def find_spec(self, fullname, path=None, target=None):
        # Since Python 3.4, you are meant to implement find_spec() method
        # instead of find_module() and since Python 3.10 you get deprecation
        # warnings if you don't define find_spec().

        # If the module being imported is not one we have registered
        # post import hooks for, we can return immediately. We will
        # take no further part in the importing of this module.

        if not fullname in _post_import_hooks:
            return None

        # When we are interested in a specific module, we will call back
        # into the import system a second time to defer to the import
        # finder that is supposed to handle the importing of the module.
        # We set an in progress flag for the target module so that on
        # the second time through we don't trigger another call back
        # into the import system and cause a infinite loop.

        if fullname in self.in_progress:
            return None

        self.in_progress[fullname] = True

        # Now call back into the import system again.

        try:
            # This should only be Python 3 so find_spec() should always
            # exist so don't need to check.

            spec = find_spec(fullname)
            loader = getattr(spec, "loader", None)

            if loader and not isinstance(loader, _ImportHookChainedLoader):
                spec.loader = _ImportHookChainedLoader(loader)

            return spec

        finally:
            del self.in_progress[fullname]
