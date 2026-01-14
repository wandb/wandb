"""Module to facilitate adding hooks to wandb actions.

Usage:
    import trigger
    trigger.register('on_something', func)
    trigger.call('on_something', *args, **kwargs)
    trigger.unregister('on_something', func)
"""

from typing import Any, Callable

_triggers = {}


def reset():
    _triggers.clear()


def register(event: str, func: Callable):
    _triggers.setdefault(event, []).append(func)


def call(event_str: str, *args: Any, **kwargs: Any):
    for func in _triggers.get(event_str, []):
        func(*args, **kwargs)


def unregister(event: str, func: Callable):
    _triggers[event].remove(func)
