from six import integer_types, string_types, text_type


class _Type(object):
    name = ""

    # must override
    def assign(self, py_obj=None):
        raise NotImplementedError()
        # return _Type subclass

    # Safe to override
    def to_dict(self, artifact=None):
        return {"wb_type": self.name}

    # Safe to override
    @classmethod
    def init_from_dict(cls, json_dict, artifact=None):
        return cls()

    def __repr__(self):
        return "<WBType:{}>".format(self.name)

    def __eq__(self, other):
        return self is other or (
            isinstance(self, _Type)
            and isinstance(other, _Type)
            and self.to_dict() == other.to_dict()
        )


class _NeverType(_Type):
    name = "never"

    def assign(self, py_obj=None):
        return NeverType


NeverType = _NeverType()


class _AnyType(_Type):
    name = "any"

    def assign(self, py_obj=None):
        return self if py_obj is not None else NeverType


AnyType = _AnyType()


class _UnknownType(_Type):
    name = "unknown"

    def assign(self, py_obj=None):
        return TypeRegistry.type_of(py_obj, none_is_optional_unknown=True)


UnknownType = _UnknownType()


class _ConcreteType(_Type):
    def assign(self, py_obj=None):
        valid = self.types_py_obj(py_obj)
        return self if valid else NeverType

    # must override
    @staticmethod
    def types_py_obj(py_obj=None):
        raise NotImplementedError()
        # return Bool

    @classmethod
    def init_from_py_obj(cls, py_obj=None):
        if cls.types_py_obj(py_obj):
            return cls()
        else:
            raise TypeError("Cannot type python object")


class _NoneType(_ConcreteType):
    name = "none"

    @staticmethod
    def types_py_obj(py_obj=None):
        return py_obj is None


NoneType = _NoneType()


class _TextType(_ConcreteType):
    name = "text"

    @staticmethod
    def types_py_obj(py_obj=None):
        return (
            isinstance(py_obj, string_types)
            or isinstance(py_obj, text_type)
            or py_obj.__class__ == str
        )


TextType = _TextType()


class _NumberType(_ConcreteType):
    name = "number"

    @staticmethod
    def types_py_obj(py_obj=None):
        return (
            isinstance(py_obj, integer_types) and py_obj.__class__ != bool
        ) or py_obj.__class__ in [int, float, complex,]


NumberType = _NumberType()


class _BooleanType(_ConcreteType):
    name = "boolean"

    @staticmethod
    def types_py_obj(py_obj=None):
        return py_obj.__class__ == bool


BooleanType = _BooleanType()


class _ParameterizedType(_ConcreteType):
    _params = None

    # safe to override
    def __init__(self, _params=None):
        if _params is not None:
            self._assert_valid_params(_params)
            self._params = _params

    # must override
    @staticmethod
    def _validate_params(params):
        raise NotImplementedError()
        # return Bool

    # Safe to override
    def to_dict(self, artifact=None):
        res = super(_ParameterizedType, self).to_dict()
        res.update(
            {
                "params": _ParameterizedType._params_dict_to_json_dict(
                    self.params, artifact
                ),
            }
        )
        if res["params"] == {}:
            del res["params"]
        return res

    # Safe to override
    @classmethod
    def init_from_dict(cls, json_dict, artifact=None):
        return cls(
            _params=_ParameterizedType._json_dict_to_params_dict(
                json_dict.get("params", {}), artifact
            )
        )

    def __repr__(self):
        return "<WBType:{} | {}>".format(self.name, self.params)

    @property
    def params(self):
        if self._params is None:
            self._params = {}
        return self._params

    @classmethod
    def _assert_valid_params(cls, params):
        if not cls.validate_params(params):
            raise TypeError("Invalid params")

    @classmethod
    def validate_params(cls, params):
        return params.__class__ == dict and cls._validate_params(params)

    @staticmethod
    def _params_dict_to_json_dict(data, artifact=None):
        if type(data) == dict:
            return {
                key: _ParameterizedType._params_dict_to_json_dict(data[key], artifact)
                for key in data
            }
        elif isinstance(data, _Type):
            return data.to_dict(artifact)
        elif type(data) in [set, frozenset, tuple]:
            return list(data)
        else:
            return data

    @staticmethod
    def _json_dict_to_params_dict(json_dict, artifact=None):
        if type(json_dict) == dict:
            if "wb_type" in json_dict:
                return TypeRegistry.type_from_dict(json_dict, artifact)
            else:
                return {
                    key: _ParameterizedType._json_dict_to_params_dict(
                        json_dict[key], artifact
                    )
                    for key in json_dict
                }
        else:
            return json_dict


class UnionType(_ParameterizedType):
    name = "union"

    # Free to define custom initializer for best UX
    def __init__(self, dtypes=None, _params=None):
        if _params is None:
            _params = {"allowed_types": dtypes}
        self._assert_valid_params(_params)
        _params["allowed_types"] = UnionType._flatten_types(_params["allowed_types"])
        _params["allowed_types"].sort(key=str)
        self._params = _params

    @staticmethod
    def types_py_obj(py_obj=None):
        # No standard type would automatically become a union
        return False

    def assign(self, py_obj=None):
        resolved_types = []
        valid = False
        unknown_count = 0

        for allowed_type in self.params.get("allowed_types", []):
            if valid:
                resolved_types.append(allowed_type)
            else:
                if isinstance(allowed_type, _UnknownType):
                    unknown_count += 1
                else:
                    assigned_type = allowed_type.assign(py_obj)
                    if assigned_type == NeverType:
                        resolved_types.append(allowed_type)
                    else:
                        resolved_types.append(assigned_type)
                        valid = True

        if not valid:
            if unknown_count == 0:
                return NeverType
            else:
                unknown_count -= 1
                resolved_types.append(UnknownType.assign(py_obj))

        for _ in range(unknown_count):
            resolved_types.append(UnknownType)

        resolved_types = UnionType._flatten_types(resolved_types)
        resolved_types.sort(key=str)
        return self.__class__(resolved_types)

    @staticmethod
    def _validate_params(params):
        allowed_types = params.get("allowed_types", [])
        return len(allowed_types) > 1 and all(
            [isinstance(allowed_type, _Type) for allowed_type in allowed_types]
        )

    @staticmethod
    def _flatten_types(allowed_types):
        final_types = []
        for allowed_type in allowed_types:
            if isinstance(allowed_type, UnionType):
                internal_types = UnionType._flatten_types(
                    allowed_type.params["allowed_types"]
                )
                for internal_type in internal_types:
                    final_types.append(internal_type)
            else:
                final_types.append(allowed_type)
        return final_types


def OptionalType(wb_type):  # noqa: N802
    return UnionType([wb_type, NoneType])


class ObjectType(_ParameterizedType):
    name = "object"

    # Free to define custom initializer for best UX
    def __init__(self, clss=None, _params=None):
        if _params is None:
            _params = {"class_name": clss.__name__}
        self._assert_valid_params(_params)
        self._params = _params

    def assign(self, py_obj=None):
        if py_obj.__class__.__name__ == self.params["class_name"]:
            return self
        else:
            return NeverType

    @classmethod
    def init_from_py_obj(cls, py_obj=None):
        return cls(py_obj.__class__)

    @staticmethod
    def types_py_obj(py_obj=None):
        return True

    @staticmethod
    def _validate_params(params):
        return len(params.get("class_name")) > 0


class ListType(_ParameterizedType):
    name = "list"

    # Free to define custom initializer for best UX
    def __init__(self, dtype=None, _params=None):
        if _params is None:
            _params = {"element_type": dtype}
        self._assert_valid_params(_params)
        self._params = _params

    @classmethod
    def init_from_py_obj(cls, py_obj=None):
        py_obj = list(py_obj)

        elm_type = UnknownType
        for item in py_obj:
            _elm_type = elm_type.assign(item)
            if _elm_type is None:
                raise TypeError(
                    "List contained incompatible types. Expected {} found {}".format(
                        elm_type, item
                    )
                )
            elm_type = _elm_type

        return cls(elm_type)

    @staticmethod
    def types_py_obj(py_obj=None):
        return py_obj.__class__ in [list, tuple, set, frozenset]

    @staticmethod
    def _validate_params(params):
        return isinstance(params["element_type"], _Type)

    def assign(self, py_obj=None):
        if not self.types_py_obj(py_obj):
            return NeverType

        new_element_type = self.params["element_type"]
        for obj in py_obj:
            for obj in py_obj:
                new_element_type = new_element_type.assign(obj)
                if new_element_type == NeverType:
                    return NeverType
        return ListType(new_element_type)


class KeyPolicy:
    EXACT = "E"  # require exact key match
    SUBSET = "S"  # all known keys are optional and unknown keys are disallowed
    UNRESTRICTED = "U"  # all known keys are optional and unknown keys are Unknown


class DictType(_ParameterizedType):
    name = "dictionary"

    # Free to define custom initializer for best UX
    def __init__(self, type_map, policy=KeyPolicy.EXACT, _params=None):
        if _params is None:
            new_type_map = {}
            for key in type_map:
                if type_map[key].__class__ == dict:
                    new_type_map[key] = DictType(type_map[key], policy)
                else:
                    new_type_map[key] = type_map[key]
            _params = {"type_map": new_type_map, "policy": policy}
        self._assert_valid_params(_params)
        self._params = _params

    @staticmethod
    def types_py_obj(py_obj=None):
        return py_obj.__class__ == dict

    @classmethod
    def init_from_py_obj(cls, py_obj=None):
        return cls(
            {
                key: TypeRegistry.type_of(py_obj[key], none_is_optional_unknown=True)
                for key in py_obj
            },
            KeyPolicy.EXACT,
        )

    @staticmethod
    def _validate_params(params):
        type_map = params.get("type_map", {})
        policy = params.get("policy")

        return all(
            [isinstance(type_map[key], _Type) for key in type_map]
        ) and policy in [KeyPolicy.EXACT, KeyPolicy.SUBSET, KeyPolicy.UNRESTRICTED]

    def assign(self, py_obj=None):
        if not self.types_py_obj(py_obj):
            return NeverType

        new_type_map = {}
        type_map = self.params.get("type_map", {})
        policy = self.params.get("policy", KeyPolicy.EXACT)

        for key in type_map:
            if key in py_obj:
                new_type = type_map[key].assign(py_obj[key])
                if new_type == NeverType:
                    return NeverType
                else:
                    new_type_map[key] = new_type
            else:
                # Treat a missing key as if it is a None value.
                new_type = type_map[key].assign(None)
                if new_type == NeverType:
                    if policy in [KeyPolicy.EXACT]:
                        return NeverType
                    elif policy in [KeyPolicy.SUBSET, KeyPolicy.UNRESTRICTED]:
                        new_type_map[key] = type_map[key]
                else:
                    new_type_map[key] = new_type

        for key in py_obj:
            if key not in new_type_map:
                if policy in [KeyPolicy.EXACT, KeyPolicy.SUBSET]:
                    return NeverType
                elif policy in [KeyPolicy.UNRESTRICTED]:
                    if py_obj[key].__class__ == dict:
                        new_type_map[key] = DictType(py_obj[key], policy)
                    else:
                        new_type_map[key] = TypeRegistry.type_of(
                            py_obj[key], none_is_optional_unknown=True
                        )

        return DictType(new_type_map, policy)


class ConstType(_ParameterizedType):
    name = "const"

    # Free to define custom initializer for best UX
    def __init__(self, val, _params=None):
        if _params is None:
            _params = {"val": val}
        self._assert_valid_params(_params)
        self._params = _params

    @staticmethod
    def types_py_obj(py_obj=None):
        return py_obj.__class__ in [str, bool, int, float]

    @classmethod
    def init_from_py_obj(cls, py_obj=None):
        res = super(ConstType, cls).init_from_py_obj(py_obj)
        res.params["val"] = py_obj
        return res

    @staticmethod
    def _validate_params(params):
        return ConstType.types_py_obj(params.get("val"))

    def assign(self, py_obj=None):
        if not self.types_py_obj(py_obj):
            return NeverType

        valid = self.params.get("val") == py_obj
        return self if valid else NeverType


class TypeRegistry:
    _types = None

    @staticmethod
    def types():
        if TypeRegistry._types is None:
            TypeRegistry._types = {}
        return TypeRegistry._types

    @staticmethod
    def add(wb_type):
        assert issubclass(wb_type, _Type)
        return TypeRegistry.types().update({wb_type.name: wb_type})

    @staticmethod
    def type_of(py_obj, none_is_optional_unknown=False):
        types = TypeRegistry.types()
        _type = None
        for key in types:
            if (
                types[key] != ConstType
                and types[key] != ObjectType
                and issubclass(types[key], _ConcreteType)
                and types[key].types_py_obj(py_obj)
            ):
                _type = types[key].init_from_py_obj(py_obj)

        # Default fallback
        if _type is None:
            _type = ObjectType.init_from_py_obj(py_obj)

        if isinstance(_type, _NoneType) and none_is_optional_unknown:
            _type = OptionalType(UnknownType)
        return _type

    @staticmethod
    def type_from_dict(json_dict, artifact=None):
        wb_type = json_dict.get("wb_type")
        if wb_type is None:
            TypeError("json_dict must contain `wb_type` key")
        return TypeRegistry.types()[wb_type].init_from_dict(json_dict, artifact)


# Generic Types
TypeRegistry.add(_NeverType)
TypeRegistry.add(_AnyType)
TypeRegistry.add(_UnknownType)

# Concrete Types
TypeRegistry.add(_NoneType)
TypeRegistry.add(_TextType)
TypeRegistry.add(_NumberType)
TypeRegistry.add(_BooleanType)

# Parametrized Types
TypeRegistry.add(ListType)
TypeRegistry.add(DictType)
TypeRegistry.add(UnionType)
TypeRegistry.add(ObjectType)
TypeRegistry.add(ConstType)

# TypeRegistry.add(OptionalType) # don't register as it is a function

# Export ParameterizedType for others to use
ParameterizedType = _ParameterizedType

__all__ = [
    "TypeRegistry",
    "NeverType",
    "UnknownType",
    "AnyType",
    "NoneType",
    "TextType",
    "NumberType",
    "BooleanType",
    "ListType",
    "DictType",
    "KeyPolicy",
    "UnionType",
    "ObjectType",
    "ConstType",
    "OptionalType",
    "ParameterizedType",
]
