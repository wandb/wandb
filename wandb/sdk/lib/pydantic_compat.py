"""
Pydantic compatibility layer to support both v1 and v2 without changing API signatures.
This file defines shims that allow v2-style code to work with v1 internals.
"""

import functools
import inspect
import re
import sys
import types
import uuid
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
    get_type_hints,
)

import pydantic
from pydantic.version import VERSION as PYDANTIC_VERSION

is_v2 = int(PYDANTIC_VERSION[0]) >= 2

# Import directly from appropriate pydantic version
if is_v2:
    from pydantic import (
        AliasChoices,
        BaseModel,
        ConfigDict,
        Field,
        computed_field,
        field_validator,
        model_validator,
    )
    from pydantic_core import SchemaValidator, core_schema

    def validate_url(url: str) -> None:
        """Validate a URL string."""
        url_validator = SchemaValidator(
            core_schema.url_schema(
                allowed_schemes=["http", "https"],
                strict=True,
            )
        )
        url_validator.validate_python(url)

    # Just re-export everything since we're already using v2
    __all__ = [
        "AliasChoices",
        "BaseModel",
        "ConfigDict",
        "Field",
        "computed_field",
        "field_validator",
        "model_validator",
        "validate_url",
        "v2_compat_model",
    ]

    # Simple passthrough function for v2
    def v2_compat_model(cls):
        """Identity decorator for Pydantic v2 models."""
        return cls

else:
    # For v1, we need to create compatibility versions of these
    from pydantic import (
        BaseModel as PydanticBaseModel,
        Field as PydanticField,
        validator,
        root_validator,
    )
    from pydantic.main import ModelMetaclass

    class AliasChoices:
        """Compatibility class for Pydantic v2's AliasChoices."""

        def __init__(self, *aliases):
            self.aliases = aliases

    # Make Field a perfect passthrough
    Field = PydanticField

    class ConfigDict(dict):
        """Compatibility class for Pydantic v2's ConfigDict."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            for k, v in kwargs.items():
                setattr(self, k, v)

    def _extract_field_info(field, mode=None):
        """Extract field name and pre/post status from a field_validator call."""
        field_name = field
        pre = mode == "before"
        return field_name, pre

    def field_validator(*fields, **kwargs):
        """Compatibility wrapper for Pydantic v2's field_validator in v1.

        Supports the v2 signature pattern:
            @field_validator('field_name', mode='before|after')
            @classmethod
            def validate_field(cls, value, info):
                # Access values through info.data.get()
                return value
        """
        # Extract mode (before/after)
        mode = kwargs.pop("mode", None)

        def decorator(func):
            # Handle the case when func is a classmethod
            is_classmethod = isinstance(func, classmethod)
            if is_classmethod:
                actual_func = func.__func__
            else:
                actual_func = func

            # Check if the function expects an info parameter
            try:
                func_sig = inspect.signature(actual_func)
                has_info_param = "info" in func_sig.parameters
            except (ValueError, TypeError):
                # If we can't get signature, assume no info param
                has_info_param = False

            # Create a v1-compatible validator for each field
            for field in fields:
                field_name = field
                pre = mode == "before"  # True for 'before', False for 'after' or None

                # Special handling for 'after' validators
                # In v1, non-pre (post) validators work differently than in v2
                # They receive all values and must return all values
                if mode == "after":

                    @functools.wraps(actual_func)
                    def wrapper(cls, values):
                        # Create v2-style info object
                        class InfoWrapper:
                            def __init__(self, data):
                                self.data = data or {}

                        # For after mode, we need to extract the field value
                        # and update it in the values dict after validation
                        if field_name in values:
                            # Only validate if the field exists
                            value = values[field_name]

                            # Call the validator with the actual function
                            if has_info_param:
                                info = InfoWrapper(values)
                                new_value = actual_func(cls, value, info)
                            else:
                                new_value = actual_func(cls, value)

                            # Update the value in the values dict
                            values[field_name] = new_value

                        return values

                    # Apply validator with v1 form
                    v_kwargs = {"allow_reuse": True, "always": True}
                    v_kwargs.update(kwargs)
                    decorated = validator(field_name, pre=pre, **v_kwargs)(wrapper)
                else:
                    # For 'before' validators, use the standard field validator
                    @functools.wraps(actual_func)
                    def wrapper(cls, value, values=None, **kw):
                        if has_info_param:
                            # Create info-like object to pass to the original function
                            class InfoWrapper:
                                def __init__(self, data):
                                    self.data = data or {}

                            info = InfoWrapper(values)
                            return actual_func(cls, value, info)
                        else:
                            return actual_func(cls, value)

                    # Apply validator with v1 form
                    v_kwargs = {"allow_reuse": True, "always": True}
                    v_kwargs.update(kwargs)
                    decorated = validator(field_name, pre=pre, **v_kwargs)(wrapper)

                # If original was a classmethod, restore that
                if is_classmethod:
                    decorated = classmethod(decorated)

                func = decorated

            return func

        # Handle case when decorator is used without parentheses
        if len(fields) == 1 and callable(fields[0]) and not isinstance(fields[0], str):
            func = fields[0]
            fields = []
            return decorator(func)

        return decorator

    def model_validator(mode="after", **kwargs):
        """
        Compatibility wrapper for Pydantic v2's model_validator in v1.

        Supports the v2 signature pattern:
            @model_validator(mode='before|after')
            @classmethod
            def validate_model(cls, data):  # For 'before'
                return data

            # OR

            @model_validator(mode='after')
            def validate_model(self):  # For 'after', operates on instance
                return self
        """
        # Make mode a keyword arg to handle both styles
        if isinstance(mode, str):
            mode_val = mode
            # Only add allow_reuse if not already present in kwargs
            if "allow_reuse" not in kwargs:
                kwargs["allow_reuse"] = True
        elif callable(mode):  # Called as @model_validator without args
            func = mode
            mode_val = "after"  # Default

            # Create a name that's unique for each function to avoid conflicts
            unique_id = str(uuid.uuid4())

            # Create the proper root validator that adapts self -> cls, values
            @root_validator(pre=False, allow_reuse=True)
            def wrapped_validator(cls, values):
                # Create a self-like object with all the values as attributes
                obj = type("ProxyModel", (), values)()

                # Call the original validator with the proxy object
                result = func(obj)

                # If the validator returned self, convert back to values dict
                if result is obj:
                    return values
                elif isinstance(result, dict):
                    return result
                else:
                    # This is an unusual case, but we'll handle it
                    return values

            # Add a unique attribute to the function to prevent duplication
            setattr(wrapped_validator, f"_unique_id_{unique_id}", True)

            return wrapped_validator
        else:
            mode_val = kwargs.pop("mode", "after")
            # Only add allow_reuse if not already present in kwargs
            if "allow_reuse" not in kwargs:
                kwargs["allow_reuse"] = True

        pre = mode_val == "before"

        def decorator(func):
            # Create a name that's unique for each function to avoid conflicts
            unique_id = str(uuid.uuid4())

            # Check if this is a method that takes 'self' as first parameter
            is_instance_method = False
            try:
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                is_instance_method = len(params) > 0 and params[0] == "self"
            except (ValueError, TypeError):
                # If we can't inspect, assume it's not an instance method
                pass

            if is_instance_method:
                # For instance methods (self), create a wrapper that converts to (cls, values)
                wrapper_kwargs = kwargs.copy()
                # Set allow_reuse=True, but don't override if already present
                wrapper_kwargs.setdefault("allow_reuse", True)

                @root_validator(pre=pre, **wrapper_kwargs)
                def wrapped_validator(cls, values):
                    # Create a self-like object with all the values as attributes
                    obj = type("ProxyModel", (), values)()

                    # Call the original validator with the proxy object
                    result = func(obj)

                    # If the validator returned self, convert back to values dict
                    if result is obj:
                        return values
                    elif isinstance(result, dict):
                        return result
                    else:
                        # This is an unusual case, but we'll handle it
                        return values

                # Add a unique attribute to the function to prevent duplication
                setattr(wrapped_validator, f"_unique_id_{unique_id}", True)

                return wrapped_validator
            else:
                # For class methods (cls, data), use as-is
                wrapper_kwargs = kwargs.copy()
                # Set allow_reuse=True, but don't override if already present
                wrapper_kwargs.setdefault("allow_reuse", True)

                wrapped_validator = root_validator(pre=pre, **wrapper_kwargs)(func)

                # Add a unique attribute to the function to prevent duplication
                setattr(wrapped_validator, f"_unique_id_{unique_id}", True)

                return wrapped_validator

        return decorator

    # Fixed computed_field to properly handle both decorator styles
    def computed_field(func=None, **kwargs):
        """
        Compatibility wrapper for Pydantic v2's computed_field in v1.
        In v1, this becomes a regular @property.

        Supports both:
            @computed_field
            @property
            def my_property(self): ...

            @computed_field()
            @property
            def my_property(self): ...
        """

        def decorator(f):
            # If already a property, return it
            if isinstance(f, property):
                return f
            # Otherwise convert it to a property
            return property(f)

        # Handle both decorator styles
        if func is not None:
            return decorator(func)
        return decorator

    def validate_url(url: str) -> None:
        """Validate a URL string for Pydantic v1."""
        # Simple URL validation for v1
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"URL must start with http:// or https://: {url}")

        # Basic URL validation
        url_pattern = re.compile(
            r"^(http|https)://"  # scheme
            r"([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}|"  # domain
            r"localhost|"  # localhost
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"  # IP
            r"(:\d+)?"  # port
            r"(/.*)?$"  # path
        )
        if not url_pattern.match(url):
            raise ValueError(f"Invalid URL: {url}")

    # Create a base model that handles both v1 and v2 style definitions
    class BaseModel(PydanticBaseModel):
        """Base model class that works with both v1 and v2 style definitions."""

        def __init_subclass__(cls, **kwargs):
            # Handle validate_assignment as a class parameter in __init_subclass__
            validate_assignment = kwargs.pop("validate_assignment", None)
            super().__init_subclass__(**kwargs)

            # Set up Config if model_config is provided
            if hasattr(cls, "model_config"):
                config_dict = cls.model_config

                # Create Config class if it doesn't exist
                if not hasattr(cls, "Config"):
                    cls.Config = type("Config", (), {})

                # Copy attributes from model_config to Config
                for key, value in config_dict.items():
                    setattr(cls.Config, key, value)

                # Handle validate_assignment
                if validate_assignment is not None:
                    cls.Config.validate_assignment = validate_assignment

        @property
        def model_fields_set(self):
            """
            Return a set of fields that have been explicitly set.
            This is a compatibility property for Pydantic v1 to mimic v2's model_fields_set.
            """
            return getattr(self, "__model_fields_set", set())

        def model_copy(self, *, update=None, **kwargs):
            """Create a copy of the model instance, optionally updating some attributes.

            This is a compatibility method for Pydantic v1 to mimic v2's model_copy.

            Args:
                update: A dictionary of attributes to update
                **kwargs: Attribute updates specified as keyword arguments

            Returns:
                A new model instance with specified updates
            """
            if update is None:
                update = {}

            # Combine update dict and kwargs
            update_data = {**update, **kwargs}

            # If using Pydantic v2, use native model_copy if available
            if hasattr(super(), "model_copy"):
                return super().model_copy(update=update_data)

            # For v1, recreate by copying the model's dict and updating values
            model_data = self.dict()
            model_data.update(update_data)
            return self.__class__(**model_data)

        def model_dump(self, **kwargs):
            """
            Compatibility method for Pydantic v1 to mimic v2's model_dump.
            In v1, this is equivalent to dict() but also includes computed properties.

            Args:
                **kwargs: Options passed to the dict method
                    - exclude_none: Whether to exclude fields with None values

            Returns:
                A dictionary of the model's fields and computed properties
            """
            # Handle exclude_none separately since it's named differently in v1
            exclude_none = kwargs.pop("exclude_none", False)

            # Start with regular fields from dict()
            result = self.dict(**kwargs)

            # Get all computed properties (those with @property decorator)
            for name in dir(self.__class__):
                if name.startswith("_") or name in result:
                    continue

                attr = getattr(self.__class__, name, None)
                if isinstance(attr, property):
                    try:
                        # Only include properties that don't raise errors
                        value = getattr(self, name)
                        result[name] = value
                    except (AttributeError, NotImplementedError, TypeError, ValueError):
                        # Skip properties that can't be accessed or raise errors
                        pass

            # Special Pydantic attributes that should always be excluded
            exclude_fields = {
                "model_config",  # ConfigDict in v2
                "model_fields",  # Fields definition in v2
                "model_fields_set",  # Set of fields that have values in v2
                "__fields__",  # Fields definition in v1
                "__model_fields_set",  # Our internal tracking for v1
                "__pydantic_self__",  # Internal reference in some Pydantic versions
                "__pydantic_initialised__",  # Internal flag in Pydantic
            }

            # Remove special Pydantic attributes
            for field in exclude_fields:
                if field in result:
                    del result[field]

            if exclude_none:
                # Remove None values from the result
                return {k: v for k, v in result.items() if v is not None}

            return result

    def v2_compat_model(cls):
        """
        Decorator to make a Pydantic v1 model mimic v2 behavior.
        This handles cases like validate_assignment=True class parameter.
        """
        # Extract any v2 class params that need special handling
        validate_assignment = getattr(cls, "__validate_assignment__", None)

        # If Config doesn't exist, create it
        if not hasattr(cls, "Config"):
            cls.Config = type("Config", (), {})

        # Apply v2 params to Config
        if validate_assignment is not None:
            cls.Config.validate_assignment = validate_assignment

        return cls

    # Export compatibility layer
    __all__ = [
        "AliasChoices",
        "BaseModel",
        "ConfigDict",
        "Field",
        "computed_field",
        "field_validator",
        "model_validator",
        "validate_url",
        "v2_compat_model",
    ]
