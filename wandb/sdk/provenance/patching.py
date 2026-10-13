from __future__ import annotations

import dataclasses
import functools
import inspect
import time
import weakref
from collections.abc import Callable, Mapping
from typing import Any


@dataclasses.dataclass(frozen=True)
class HookContext:
    instance: object
    args: tuple[object, ...]
    kwargs: Mapping[str, object]
    started_ns: int
    result: object | None = None
    error: BaseException | None = None


Hook = Callable[[HookContext], None]


class PatchRegistry:
    def __init__(self) -> None:
        self._methods: dict[
            tuple[object, str], tuple[Any, list[tuple[Hook | None, Hook | None]]]
        ] = {}
        self.instances: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    def observe(
        self,
        owner: object,
        name: str,
        *,
        before: Hook | None = None,
        after: Hook | None = None,
    ) -> None:
        key = (owner, name)
        observer = (before, after)
        if key in self._methods:
            observers = self._methods[key][1]
            if observer not in observers:
                observers.append(observer)
            return
        descriptor = inspect.getattr_static(owner, name)
        static = isinstance(descriptor, staticmethod)
        class_method = isinstance(descriptor, classmethod)
        original = descriptor.__func__ if static or class_method else descriptor
        observers = [observer]
        self._methods[key] = (descriptor, observers)

        @functools.wraps(original)
        def wrapped(*args, **kwargs):
            instance = owner if static or not isinstance(owner, type) else args[0]
            arguments = args if static or not isinstance(owner, type) else args[1:]
            context = HookContext(instance, arguments, kwargs, time.monotonic_ns())
            for callback, _ in tuple(observers):
                if callback:
                    try:
                        callback(context)
                    except Exception:
                        pass
            try:
                result = original(*args, **kwargs)
            except BaseException as error:
                context = dataclasses.replace(context, error=error)
                raise
            else:
                context = dataclasses.replace(context, result=result)
                return result
            finally:
                for _, callback in tuple(observers):
                    if callback:
                        try:
                            callback(context)
                        except Exception:
                            pass

        replacement = (
            staticmethod(wrapped)
            if static
            else classmethod(wrapped)
            if class_method
            else wrapped
        )
        setattr(owner, name, replacement)

    def detach(self) -> None:
        for (owner, name), (original, _) in self._methods.items():
            setattr(owner, name, original)
        self._methods.clear()
        self.instances.clear()
