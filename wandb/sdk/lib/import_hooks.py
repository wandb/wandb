"""Implements a post-import hook mechanism.

Styled as per PEP-369. Note that it doesn't cope with modules being reloaded.

Note: This file is based on
https://github.com/GrahamDumpleton/wrapt/blob/1.12.1/src/wrapt/importer.py
and manual backports of later patches up to 1.15.0 in the wrapt repository
(with slight modifications).
"""

import sys
import threading
from importlib.util import find_spec
from typing import Any, Callable, Dict, Optional, Union

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


def _create_import_hook_from_string(name: str) -> Callable:
    def import_hook(module: Any) -> Callable:
        module_name, function = name.split(":")
        attrs = function.split(".")
        __import__(module_name)
        callback = sys.modules[module_name]
        for attr in attrs:
            callback = getattr(callback, attr)
        return callback(module)  # type: ignore

    return import_hook


def register_post_import_hook(
    hook: Union[str, Callable], hook_id: str, name: str
) -> None:
    # Create a deferred import hook if hook is a string name rather than
    # a callable function.

    if isinstance(hook, (str,)):
        hook = _create_import_hook_from_string(hook)

    # Automatically install the import hook finder if it has not already
    # been installed.

    with _post_import_hooks_lock:
        global _post_import_hooks_init

        if not _post_import_hooks_init:
            _post_import_hooks_init = True
            sys.meta_path.insert(0, ImportHookFinder())  # type: ignore

        # Check if the module is already imported. If not, register the hook
        # to be called after import.

        module = sys.modules.get(name, None)

        if module is None:
            _post_import_hooks.setdefault(name, {}).update({hook_id: hook})

    # If the module is already imported, we fire the hook right away. Note that
    # the hook is called outside of the lock to avoid deadlocks if code run as a
    # consequence of calling the module import hook in turn triggers a separate
    # thread which tries to register an import hook.

    if module is not None:
        hook(module)


def unregister_post_import_hook(name: str, hook_id: Optional[str]) -> None:
    # Remove the import hook if it has been registered.
    with _post_import_hooks_lock:
        hooks = _post_import_hooks.get(name)

        if hooks is not None:
            if hook_id is not None:
                hooks.pop(hook_id, None)

                if not hooks:
                    del _post_import_hooks[name]
            else:
                del _post_import_hooks[name]


def unregister_all_post_import_hooks() -> None:
    with _post_import_hooks_lock:
        _post_import_hooks.clear()


# Indicate that a module has been loaded. Any post import hooks which
# were registered against the target module will be invoked. If an
# exception is raised in any of the post import hooks, that will cause
# the import of the target module to fail.


def notify_module_loaded(module: Any) -> None:
    name = getattr(module, "__name__", None)

    with _post_import_hooks_lock:
        hooks = _post_import_hooks.pop(name, {})

    # Note that the hook is called outside of the lock to avoid deadlocks if
    # code run as a consequence of calling the module import hook in turn
    # triggers a separate thread which tries to register an import hook.
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

        if hasattr(loader, "load_module"):
            self.load_module = self._load_module
        if hasattr(loader, "create_module"):
            self.create_module = self._create_module
        if hasattr(loader, "exec_module"):
            self.exec_module = self._exec_module

    def _set_loader(self, module: Any) -> None:
        # Set module's loader to self.loader unless it's already set to
        # something else. Import machinery will set it to spec.loader if it is
        # None, so handle None as well. The module may not support attribute
        # assignment, in which case we simply skip it. Note that we also deal
        # with __loader__ not existing at all. This is to future proof things
        # due to proposal to remove the attribute as described in the GitHub
        # issue at https://github.com/python/cpython/issues/77458. Also prior
        # to Python 3.3, the __loader__ attribute was only set if a custom
        # module loader was used. It isn't clear whether the attribute still
        # existed in that case or was set to None.

        class UNDEFINED:
            pass

        if getattr(module, "__loader__", UNDEFINED) in (None, self):
            try:
                module.__loader__ = self.loader
            except AttributeError:
                pass

        if (
            getattr(module, "__spec__", None) is not None
            and getattr(module.__spec__, "loader", None) is self
        ):
            module.__spec__.loader = self.loader

    def _load_module(self, fullname: str) -> Any:
        module = self.loader.load_module(fullname)
        self._set_loader(module)
        notify_module_loaded(module)

        return module

    # Python 3.4 introduced create_module() and exec_module() instead of
    # load_module() alone. Splitting the two steps.

    def _create_module(self, spec: Any) -> Any:
        return self.loader.create_module(spec)

    def _exec_module(self, module: Any) -> None:
        self._set_loader(module)
        self.loader.exec_module(module)
        notify_module_loaded(module)


class ImportHookFinder:
    def __init__(self) -> None:
        self.in_progress: Dict = {}

    def find_module(  # type: ignore
        self,
        fullname: str,
        path: Optional[str] = None,
    ) -> Optional["_ImportHookChainedLoader"]:
        # If the module being imported is not one we have registered
        # post import hooks for, we can return immediately. We will
        # take no further part in the importing of this module.

        with _post_import_hooks_lock:
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

    def find_spec(
        self, fullname: str, path: Optional[str] = None, target: Any = None
    ) -> Any:
        # Since Python 3.4, you are meant to implement find_spec() method
        # instead of find_module() and since Python 3.10 you get deprecation
        # warnings if you don't define find_spec().

        # If the module being imported is not one we have registered
        # post import hooks for, we can return immediately. We will
        # take no further part in the importing of this module.

        with _post_import_hooks_lock:
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
            # This should only be Python 3 so find_spec() should always
            # exist so don't need to check.
            spec = find_spec(fullname)
            loader = getattr(spec, "loader", None)

            if loader and not isinstance(loader, _ImportHookChainedLoader):
                assert spec is not None
                spec.loader = _ImportHookChainedLoader(loader)  # type: ignore

            return spec

        finally:
            del self.in_progress[fullname]
