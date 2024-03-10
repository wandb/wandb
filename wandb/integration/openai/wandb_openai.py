import datetime
import inspect
import logging
import re

logger = logging.getLogger(__name__)


class WandbOpenAIBase:
    """WandbOpenAIClient is a wrapper around the openai module.

    Inspired by https://github.com/MagnivOrg/prompt-layer-library/blob/master/promptlayer/promptlayer.py based on Apache-2.0 license.
    """

    __slots__ = ["_obj", "__weakref__", "_function_name", "_provider_type"]
    wandb_run = None
    wandb_openai_resolver = None

    def __init__(
        self,
        obj,
        function_name="",
        provider_type="openai",
        wandb_run=None,
        wandb_openai_resolver=None,
    ):
        object.__setattr__(self, "_obj", obj)
        object.__setattr__(self, "_function_name", function_name)
        object.__setattr__(self, "_provider_type", provider_type)
        if wandb_run is not None:
            WandbOpenAIBase.wandb_run = wandb_run
        if wandb_openai_resolver is not None:
            WandbOpenAIBase.wandb_openai_resolver = wandb_openai_resolver

    def __getattr__(self, name):
        attr = getattr(object.__getattribute__(self, "_obj"), name)
        if not re.match(
            r"<class 'openai\..*Error'>", str(attr)
        ) and (  # fix for openai errors
            inspect.isclass(attr)
            or inspect.isfunction(attr)
            or inspect.ismethod(attr)
            or re.match(r"<class 'openai\.resources.*'>", str(type(attr)))
        ):
            return WandbOpenAIBase(
                attr,
                function_name=f'{object.__getattribute__(self, "_function_name")}.{name}',
                provider_type=object.__getattribute__(self, "_provider_type"),
            )
        return attr

    def __delattr__(self, name):
        delattr(object.__getattribute__(self, "_obj"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_obj"), name, value)

    def __call__(self, *args, **kwargs):
        request_start_time = datetime.datetime.now().timestamp()
        function_object = object.__getattribute__(self, "_obj")
        if inspect.isclass(function_object):
            return WandbOpenAIBase(
                function_object(*args, **kwargs),
                function_name=object.__getattribute__(self, "_function_name"),
                provider_type=object.__getattribute__(self, "_provider_type"),
            )
        function_response = function_object(*args, **kwargs)
        request_end_time = datetime.datetime.now().timestamp()

        try:
            loggable_dict = WandbOpenAIBase.wandb_openai_resolver(
                args,
                kwargs,
                function_response,
                request_start_time,
                request_end_time - request_start_time,
            )
            print(f"LOGGABLE DICT: {loggable_dict}")
            if loggable_dict is not None:
                WandbOpenAIBase.wandb_run.log(loggable_dict)
        except Exception as e:
            logger.warning(e)
        return function_response
