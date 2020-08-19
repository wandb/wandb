"""Module to facilitate adding hooks to wandb actions

Usage:
    import trigger
    trigger.register('on_something', func)
    trigger.call('on_something', *args, **kwargs)
    trigger.unregister('on_something', func)
"""


_triggers = {}


def reset():
    _triggers.clear()


def register(event, func):
    _triggers.setdefault(event, []).append(func)


def call(event_str, *args, **kwargs):
    for func in _triggers.get(event_str, []):
        func(*args, **kwargs)


def unregister(event, func):
    _triggers[event].remove(func)
