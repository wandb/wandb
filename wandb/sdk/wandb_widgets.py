from inspect import signature, getsource, Parameter
import functools
import queue

import wandb

_factory = {}

__all__ = ["Widget", "Knob", "Callback", "connect"]


def add_factory_callbacks(run):
    print("Factory called", _factory)
    for name, args in _factory.items():
        print("Adding the factory meths")
        connect_to_run(run, name, *args)


def connect_to_run(run, name, type, callback):
    run.add_callback(name, callback)
    sig = signature(callback)
    args = []
    for p in sig.parameters.values():
        default = p.default
        if default == Parameter.empty:
            default = None
        annotation = p.annotation
        if annotation == Parameter.empty:
            annotation = None
        args.append({"name": p.name, "default": default, "type": annotation})
    config_payload = {"args": args, "source": getsource(callback), "type": type}
    run._set_config_wandb(f"widget/{name}", config_payload)


def connect(type="callback", name=None, manual_update=False, manual_kwargs=None):
    callback_name = name
    callback_manual_update = manual_update
    callback_manual_kwargs = manual_kwargs or dict()
    callback_manual_kwargs["ctx"] = dict()
    ctx = callback_manual_kwargs["ctx"]

    def decorator(func):
        global factory
        _queue = queue.Queue()
        name = callback_name or func.__name__
        sig = signature(func)
        # Magic ctx keyword only passed if the user asked for it
        if "ctx" not in sig.parameters.keys():
            del callback_manual_kwargs["ctx"]

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if "steps" in sig.parameters.keys():
                if len(args) > 0:
                    max_steps = args[0]
                else:
                    max_steps = kwargs["steps"]
                print("Set max steps", max_steps)
                ctx["steps"] = -1
                ctx["_max_steps"] = max_steps

            # TODO: should we delete ctx from kwargs?
            callback_manual_kwargs.update(**kwargs)
            if callback_manual_update:
                _queue.put((args, callback_manual_kwargs))
            else:
                return func(*args, **callback_manual_kwargs)

        _factory[name] = (type, wrapper)
        if wandb.run is not None:
            connect_to_run(wandb.run, name, type, wrapper)

        def update_if_needed(**kwargs):
            try:
                ctx = callback_manual_kwargs.get("ctx", {})
                if ctx.get("_max_steps") is not None:
                    ctx["steps"] += 1
                    if ctx["steps"] > ctx["_max_steps"]:
                        # TODO signal the function if we're done
                        print("Reset _max_steps")
                        ctx["_max_steps"] = None
                    else:
                        print("Calling manual update: ", callback_manual_kwargs)
                        func(**callback_manual_kwargs)
                else:
                    call = _queue.get_nowait()
                    print("got manual update", call)
                    callback_manual_kwargs.update(**call[1])
                    func(*call[0], **callback_manual_kwargs)
                return True
            except queue.Empty:
                return False

        wrapper.update = update_if_needed

        return wrapper

    return decorator


class Widget:
    def __init__(self, *args, **kwargs):
        self._name = type(self).__name__
        global _factory
        _factory[self._name] = (self.type, self.update)
        if wandb.run is not None:
            connect_to_run(wandb.run, self._name, self.type, self.update)

    def update(self, *args, **kwargs):
        raise NotImplementedError

    @property
    def type(self):
        return "widget"


class Knob(Widget):
    @property
    def type(self):
        return "knob"


class Callback(Widget):
    @property
    def type(self):
        return "callback"
