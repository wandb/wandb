from six import integer_types, string_types, text_type


# TODO: Potentially remove
class TypedClassMixin(object):
    def get_type(self):
        raise NotImplementedError()


class _Type(object):
    name = ""

    # must override
    def assign(self, py_obj):
        raise NotImplementedError()
        # return None | _Type subclass

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
        return self.to_dict() == other.to_dict()


class AnyType(_Type):
    name = "any"

    def assign(self, py_obj):
        return self


class UnknownType(_Type):
    name = "unknown"

    def assign(self, py_obj):
        return TypeRegistry.type_of(py_obj, none_is_optional=True)


class _ConcreteType(_Type):
    def assign(self, py_obj):
        valid = self.types_py_obj(py_obj)
        return self if valid else None

    # must override
    @staticmethod
    def types_py_obj(py_obj):
        raise NotImplementedError()
        # return Bool

    @classmethod
    def init_from_py_obj(cls, py_obj):
        if cls.types_py_obj(py_obj):
            return cls()
        else:
            raise TypeError("Cannot type python object")


class NoneType(_ConcreteType):
    name = "none"

    @staticmethod
    def types_py_obj(py_obj):
        return py_obj is None


class TextType(_ConcreteType):
    name = "text"

    @staticmethod
    def types_py_obj(py_obj):
        return (
            isinstance(py_obj, string_types)
            or isinstance(py_obj, text_type)
            or py_obj.__class__ == str
        )


class NumberType(_ConcreteType):
    name = "number"

    @staticmethod
    def types_py_obj(py_obj):
        return isinstance(py_obj, integer_types) or py_obj.__class__ in [
            int,
            float,
            complex,
        ]


class BooleanType(_ConcreteType):
    name = "boolean"

    @staticmethod
    def types_py_obj(py_obj):
        return py_obj.__class__ == bool


class _ParameterizedType(_ConcreteType):
    _params = None

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
        new_type = cls()
        new_type.params = _ParameterizedType._json_dict_to_params_dict(
            json_dict.get("params", {}), artifact
        )
        return new_type

    @classmethod
    def init_from_params(cls, params):
        cls._assert_validate_params(params)
        res = cls()
        res._params = params
        return res

    def __repr__(self):
        return "<WBType:{} | {}>".format(self.name, self.params)

    @property
    def params(self):
        if self._params is None:
            self._params = {}
        return self._params

    @classmethod
    def _assert_validate_params(cls, params):
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

    def assign(self, py_obj):
        resolved_types = []
        valid = False
        unknown_count = 0

        for allowed_type in self.py_obj.params.get("allowed_types", []):
            if isinstance(allowed_type, UnknownType):
                unknown_count += 1
            else:
                assigned_type = allowed_type.assign(py_obj)
                if assigned_type is not None:
                    resolved_types.append(assigned_type)
                    valid = True
                    break

        if not valid:
            if unknown_count == 0:
                return None
            else:
                unknown_count -= 1
                resolved_types.append(OptionalType().assign(py_obj))

        for _ in range(unknown_count):
            resolved_types.append(UnknownType())

        return self.__class__.init_from_params(
            {"allowed_types": UnionType._flatten_types(resolved_types)}
        )

    @staticmethod
    def _validate_params(cls, params):
        allowed_types = params.get("allowed_types", [])
        return len(allowed_types) > 0 and all(
            [isinstance(allowed_type, _Type) for allowed_type in allowed_types]
        )

    @staticmethod
    def _flatten_types(allowed_types):
        final_types = []
        non_params_type_set = set()
        for allowed_type in allowed_types:
            if isinstance(allowed_type, UnionType):
                internal_types = UnionType._flatten_types(
                    allowed_type.params["allowed_types"]
                )
                for internal_type in internal_types:
                    if not isinstance(internal_type, _ParameterizedType):
                        non_params_type_set.add(internal_type)
                    else:
                        final_types.append(internal_type)
            else:
                if not isinstance(allowed_type, _ParameterizedType):
                    non_params_type_set.add(allowed_type)
                else:
                    final_types.append(allowed_type)
        return final_types + list(non_params_type_set)


def OptionalType(wb_type):  # noqa: N802
    return UnionType.init_from_params({"allowed_types": [wb_type, NoneType]})


class ObjectType(_ParameterizedType):
    name = "object"

    def assign(self, py_obj):
        if py_obj.__class__.__name__ == self.params["class_name"]:
            return self
        else:
            return None

    @classmethod
    def init_from_py_obj(cls, py_obj):
        res = super(cls, _ParameterizedType).init_from_py_obj(py_obj)
        res.params["class_name"] = py_obj.__class__.__name__
        return res

    @staticmethod
    def types_py_obj(py_obj):
        return True

    @staticmethod
    def _validate_params(params):
        return len(params.get("class_name")) > 0


class ListType(_ParameterizedType):
    name = "list"

    @classmethod
    def init_from_py_obj(cls, py_obj):
        res = super(cls, _ParameterizedType).init_from_py_obj(py_obj)
        py_obj = list(py_obj)

        elm_type = UnknownType()
        for item in py_obj:
            _elm_type = elm_type.assign(item)
            if _elm_type is None:
                raise TypeError(
                    "List contained incompatible types. Expected {} found {}".format(
                        elm_type, item
                    )
                )
            elm_type = _elm_type
        res.params["element_type"] = elm_type

        return res

    @staticmethod
    def types_py_obj(py_obj):
        return py_obj.__class__ in [list, tuple, set, frozenset]

    @staticmethod
    def _validate_params(params):
        return isinstance(params["element_type"], _Type)

    def assign(self, py_obj):
        new_element_type = self.params["element_type"].assign(py_obj)
        if new_element_type is not None:
            return ListType.init_from_params({"element_type": new_element_type})
        else:
            return None


class DictPolicy:
    EXACT: 0  # require exact key match
    SUBSET: 1  # treat all known keys as optional and unknown keys disallowed
    NARROW: 2  # treat all known keys as optional and unknown keys as Unknown


class DictType(_ParameterizedType):
    name = "dictionary"

    @staticmethod
    def types_py_obj(py_obj):
        return py_obj.__class__ == dict

    @classmethod
    def init_from_py_obj(cls, py_obj):
        res = super(_ParameterizedType, cls).init_from_py_obj(py_obj)
        res.params["value_types"] = {
            key: TypeRegistry.type_of(py_obj[key], none_is_optional=True)
            for key in py_obj
        }
        res.params["policy"] = DictPolicy.EXACT

        return res

    @staticmethod
    def _validate_params(params):
        value_types = params.get("value_types", {})
        policy = params.get("policy")

        return all(
            [isinstance(value_types[key], _Type) for key in value_types]
        ) and policy in [DictPolicy.EXACT, DictPolicy.SUBSET, DictPolicy.NARROW]

    def assign(self, py_obj):
        new_types = {}
        value_types = self.params.get("value_types", {})
        policy = self.params.get("policy", DictPolicy.EXACT)

        for key in value_types:
            if key in py_obj:
                new_type = value_types[key].assign(py_obj[key])
                if new_type is None:
                    return None
                else:
                    new_types[key] = new_type
            elif policy == DictPolicy.EXACT:
                return None

        if policy == DictPolicy.EXACT:
            if len(py_obj.keys()) != len(value_types.keys()):
                return None
        elif policy == DictPolicy.SUBSET:
            for key in py_obj:
                if key not in new_types:
                    return None
        elif policy == DictPolicy.NARROW:
            for key in py_obj:
                if key not in new_types:
                    new_types[key] = TypeRegistry.type_of(
                        py_obj[key], none_is_optional=True
                    )

        return DictType.init_from_params({"value_types": new_types, "policy": policy})


class ConstType(_ParameterizedType):
    @staticmethod
    def types_py_obj(py_obj):
        return py_obj.__class__ in [str, bool, int, float]

    @classmethod
    def init_from_py_obj(cls, py_obj):
        res = super(cls, _ParameterizedType).init_from_py_obj(py_obj)
        res.params["py_obj"] = py_obj
        return res

    @staticmethod
    def _validate_params(params):
        return ConstType.types_py_obj(params.get("py_obj"))

    def assign(self, py_obj):
        valid = self.params.get("py_obj") == py_obj
        return self if valid else None


# TODO: add "frozen" param to assign call


class TypeRegistry:
    """Singleton-like Registry"""

    _types = None

    @staticmethod
    def types():
        if TypeRegistry._types is None:
            TypeRegistry._types = {}
        return TypeRegistry._types

    @staticmethod
    def add(wb_type):
        assert issubclass(wb_type, _Type)
        return TypeRegistry.types().update({wb_type.name(): wb_type})

    @staticmethod
    def type_of(py_obj, none_is_optional=False):
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
            # TODO: Probably remove this first block
            if isinstance(py_obj, TypedClassMixin):
                _type = py_obj.get_type()
            else:
                _type = ObjectType.init_from_py_obj(py_obj)

        if isinstance(_type, NoneType) and none_is_optional:
            _type = OptionalType(_type)
        return _type

    @staticmethod
    def type_from_dict(json_dict, artifact=None):
        wb_type = json_dict.get("wb_type")
        if wb_type is None:
            TypeError("json_dict must contain `wb_type` key")
        return TypeRegistry.types()[wb_type].init_from_dict(json_dict, artifact)


TypeRegistry.add(NoneType)
TypeRegistry.add(TextType)
TypeRegistry.add(NumberType)
TypeRegistry.add(BooleanType)
TypeRegistry.add(ListType)
TypeRegistry.add(DictType)
TypeRegistry.add(UnionType)
TypeRegistry.add(OptionalType)
TypeRegistry.add(UnknownType)
TypeRegistry.add(AnyType)
TypeRegistry.add(ObjectType)
TypeRegistry.add(ConstType)
