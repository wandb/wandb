from six import integer_types, string_types, text_type

class _Type(object):
    name = ""

    def assign(self, py_obj):
        raise NotImplementedError()
        # return None | _Type subclass

    def __repr__(self):
        return "<WBType:{}>".format(self.name)

class AnyType(_Type):
    name = "any"

    def assign(self, py_obj):
        return self

class UnknownType(_Type):
    name = "unknown"

    def assign(self, py_obj):
        return self if py_obj is not None else Optional(UnknownType())

class _PythonObjectType(_Type):
    def assign(self, py_obj):
        valid = self.types_py_obj(py_obj)
        return self if valid else None

    @classmethod
    def init_from_py_obj(cls, py_obj):
        if cls.types_py_obj(py_obj):
            return cls()
        else:
            raise TypeError("Cannot type python object")

    @staticmethod
    def types_py_obj(py_obj):
        raise NotImplementedError()
        # return Bool

class NoneType(_PythonObjectType):
    name = "none"

    @staticmethod
    def types_py_obj(py_obj):
        return py_obj is None


class TextType(_PythonObjectType):
    name = "text"

    @staticmethod
    def types_py_obj(py_obj):
        return isinstance(py_obj, string_types) or isinstance(py_obj, text_type) or py_obj.__class__ == str


class NumberType(_PythonObjectType):
    name = "number"

    @staticmethod
    def types_py_obj(py_obj):
        return isinstance(py_obj, integer_types) or py_obj.__class__ in [int, float, complex]


class BooleanType(_PythonObjectType):
    name = "boolean"

    @staticmethod
    def types_py_obj(py_obj):
        return py_obj.__class__ == bool


class _SpecifiedType(_Type):
    _spec = None
    
    @classmethod
    def init_from_spec(cls, spec):
        cls._assert_validate_spec(spec)
        res = cls()
        res._spec = spec
        return res

    def __repr__(self):
        return "<WBType:{} | {}>".format(self.name, self.spec)

    @property
    def spec(self):
        if self._spec is None:
            self._spec = {}
        return self._spec

    @classmethod
    def _assert_validate_spec(cls, spec):
        if not cls.validate_spec(spec):
            raise TypeError("Invalid Spec")

    @classmethod
    def validate_spec(cls, spec):
        return spec.__class__ == dict and cls._validate_spec(spec)

    @classmethod
    def _validate_spec(cls, spec):
        raise NotImplementedError()
        # return Bool


class UnionType(_SpecifiedType):
    name = "union"

    def assign(self, py_obj):
        resolved_types = []
        valid = False
        unknown_count = 0

        for allowed_type in self.py_obj.spec.get("allowed_types", []):
            if isinstance(allowed_type, UnknownType):
                unknown_count += 1
            else:
                assigned_type = allowed_type.assign(py_obj)
                if isinstance(assigned_type, UnionType):
                    for sub_type in assigned_type.spec["allowed_types"]:
                        resolved_types.append(sub_type)
                else:
                    resolved_types.append(assigned_type)
                if assigned_type is not None:
                    valid = True
                    break
        
        if not valid:
            if unknown_count == 0:
                return None
            else:
                unknown_count -= 1
                resolved_types.append(TypeRegistry.type_of(py_obj))
        
        for _ in range(unknown_count):
            resolved_types.append(UnknownType())

        # flatten

        
        return self.__class__.init_from_spec({
            "allowed_types": resolved_types
        })

    @staticmethod
    def _validate_spec(cls, spec):
        allowed_types = spec.get("allowed_types", [])
        return len(allowed_types) > 0 and all([
            isinstance(allowed_type, _Type)
            for allowed_type in allowed_types
        ])


def OptionalType(wb_type):
    return Union.init_from_spec({
        "allowed_types": [wb_type, NoneType]
    })


class ObjectType(_PythonObjectType, _SpecifiedType):
    name = "object"

    @classmethod
    def init_from_py_obj(cls, py_obj):
        res = super(_PythonObjectType, ObjectType).init_from_py_obj()
        res.spec["class_name"] = py_obj.__class__.__name__
        return res

    @staticmethod
    def types_py_obj(py_obj):
        return True
    
    @classmethod
    def _validate_spec(cls, spec):
        return len(spec.get("class_name")) > 0

    def assign(self, py_obj):
        if py_obj.__class__.__name__ == self.spec["class_name"]:
            return self
        else:
            return None

class ListType(_PythonObjectType, _SpecifiedType):
    name = "list"

    @classmethod
    def init_from_py_obj(cls, py_obj):
        res = super(_PythonObjectType, ObjectType).init_from_py_obj()
        res.spec["class_name"] = py_obj.__class__.__name__

        # elm_type = _WBType()
        # for item in py_list:
        #     _elm_type = elm_type.type_by_assignment(item)
        #     if _elm_type is None:
        #         raise TypeError(
        #             "List contained incompatible types. Expected {} found {}".format(
        #                 elm_type, item
        #             )
        #         )
        #     elm_type = _elm_type
        # self.schema["element_type"] = elm_type


        return res

    @staticmethod
    def types_py_obj(py_obj):
        return True
    
    @classmethod
    def _validate_spec(cls, spec):
        return len(spec.get("class_name")) > 0

    def assign(self, py_obj):
        if py_obj.__class__.__name__ == self.spec["class_name"]:
            return self
        else:
            return None

# TODO Const type

class _WBListType(_WBType):
    name = "list"

    def __init__(self, py_list=None):
        if py_list is None:
            py_list = []
        super(_WBListType, self).__init__(py_list)
        elm_type = _WBType()
        for item in py_list:
            _elm_type = elm_type.type_by_assignment(item)
            if _elm_type is None:
                raise TypeError(
                    "List contained incompatible types. Expected {} found {}".format(
                        elm_type, item
                    )
                )
            elm_type = _elm_type
        self.schema["element_type"] = elm_type

    def type_by_assignment(self, py_obj=None, wb_type=None):
        other_type = super(_WBListType, self).type_by_assignment(py_obj, wb_type)
        new_list_type = None
        if other_type is not None:
            new_elm_type = self.schema["element_type"].type_by_assignment(
                py_obj, other_type.schema["element_type"]
            )
            if new_elm_type is not None:
                new_list_type = _WBListType()
                new_list_type.schema["element_type"] = new_elm_type
        return new_list_type


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

    def type_of(py_obj):
        types = TypeRegistry.types()
        _type = None
        for key in types:
            if issubclass(types[key], _PythonObjectType) and types[key].types_py_obj(py_obj):
                _type = types[key].init_from_py_obj(py_obj)
        return _type


TypeRegistry.add(NoneType)
TypeRegistry.add(TextType)
TypeRegistry.add(NumberType)
TypeRegistry.add(BooleanType)
TypeRegistry.add(UnionType)
TypeRegistry.add(OptionalType)
TypeRegistry.add(UnknownType)
TypeRegistry.add(AnyType)
TypeRegistry.add(ObjectType) # must be last







class _WBType(object):
    name = "none"
    schema = None

    def __init__(self, py_obj=None):
        self.schema = {}

    @staticmethod
    def from_obj(py_obj):
        obj_type = py_obj.__class__  # type() does not work in py2
        if py_obj is None:
            return _WBType(py_obj)
        elif obj_type == str:
            return _WBTextType(py_obj)
        elif obj_type in [int, float, complex]:
            return _WBNumberType(py_obj)
        elif obj_type == bool:
            return _WBBooleanType(py_obj)
        elif obj_type in [list, tuple, set, frozenset]:
            py_list = list(py_obj)
            return _WBListType(py_list)
        elif obj_type == dict:
            return _WBDictType(py_obj)
        elif hasattr(py_obj, "_get_wbtype"):
            return py_obj._get_wbtype()
        else:
            return _WBObjectType(py_obj)

    @staticmethod
    def parse_dict(json_dict, artifact=None):
        wb_type = json_dict.get("wb_type")
        return _WBType._registered[wb_type].from_dict(json_dict, artifact)

    @staticmethod
    def register_type(wb_type):
        assert issubclass(wb_type, _WBType)
        if not hasattr(_WBType, "_registered"):
            _WBType._registered = {}
        _WBType._registered.update({wb_type.name: wb_type})

    def __eq__(self, other):
        # since we know that the to_dict method recursively build a jsonable dict
        # with only lists, dicts, str, bool, and int, we can use this comparison
        return self.to_dict() == other.to_dict()

    @staticmethod
    def _to_dict(data, artifact=None):
        if type(data) == dict:
            schema_dict = data
            return {
                key: _WBType._to_dict(schema_dict[key], artifact) for key in schema_dict
            }
        elif isinstance(data, _WBType):
            wbtype = data
            return wbtype.to_dict(artifact)
        elif type(data) in [set, frozenset, tuple]:
            return list(data)
        else:
            return data

    # Safe to override
    def to_dict(self, artifact=None):
        res = {
            "wb_type": self.name,
            "schema": _WBType._to_dict(self.schema, artifact),
        }
        if res["schema"] == {}:
            del res["schema"]
        return res

    @staticmethod
    def _from_dict(json_dict, artifact=None):
        if type(json_dict) == dict:
            if "wb_type" in json_dict:
                return _WBType.parse_dict(json_dict, artifact)
            else:
                return {
                    key: _WBType._from_dict(json_dict[key], artifact)
                    for key in json_dict
                }
        else:
            return json_dict

    # Safe to override
    @classmethod
    def from_dict(cls, json_dict, artifact=None):
        new_type = cls()
        new_type.schema = _WBType._from_dict(json_dict.get("schema", {}), artifact)
        return new_type

    # Safe to override
    def type_by_assignment(self, py_obj=None, wb_type=None):
        if wb_type is None:
            wb_type = _WBType.from_obj(py_obj)
        if wb_type.name == "none":
            return self
        elif self.name == "none" or self.name == wb_type.name:
            return wb_type
        else:
            return None





class _WBDictType(_WBType):
    name = "dictionary"

    def __init__(self, py_dict=None):
        if py_dict is None:
            py_dict = {}
        super(_WBDictType, self).__init__(py_dict)
        key_types = {}
        for key in py_dict:
            key_types[key] = _WBType.from_obj(py_dict[key])
        self.schema["key_types"] = key_types

    def type_by_assignment(self, py_obj=None, wb_type=None):
        # if the key exists, then it must be assign to the type
        other_type = super(_WBDictType, self).type_by_assignment(py_obj, wb_type)
        new_dict_type = None
        if other_type is not None:
            key_types = {}
            for key in self.schema["key_types"]:
                if key in other_type.schema["key_types"]:
                    new_key_type = self.schema["key_types"][key].type_by_assignment(
                        py_obj[key] if py_obj else None,
                        other_type.schema["key_types"][key],
                    )
                    if new_key_type is None:
                        return None
                else:
                    new_key_type = self.schema["key_types"][key]
                key_types[key] = new_key_type

            for key in other_type.schema["key_types"]:
                if key not in key_types:
                    key_types[key] = other_type.schema["key_types"][key]

            new_dict_type = _WBDictType()
            new_dict_type.schema["key_types"] = key_types

        return new_dict_type


# Currently only supports primitives
class _WBAllowableType(_WBType):
    name = "allowable"

    def __init__(self, value_list=None):
        if value_list is None:
            value_list = []
        super(_WBAllowableType, self).__init__(value_list)
        self.schema["allowed_values"] = set(value_list)

    def type_by_assignment(self, py_obj=None, wb_type=None):
        if py_obj is None or py_obj in self.schema["allowed_values"]:
            return self
        else:
            other_type = super(_WBAllowableType, self).type_by_assignment(
                py_obj, wb_type
            )
            if (
                other_type is not None
                and len(
                    other_type.schema["allowed_values"] - self.schema["allowed_values"]
                )
                == 0
            ):
                return self
            else:
                return None

    @classmethod
    def from_dict(cls, json_dict, artifact=None):
        new_type = cls()
        new_type.schema["allowed_values"] = set(json_dict["schema"]["allowed_values"])
        return new_type


class _WBClassesIdType(_WBAllowableType):
    name = "wandb.Classes_id"

    def __init__(self, wb_classes=None):
        if wb_classes is None:
            wb_classes = Classes({})
        super(_WBClassesIdType, self).__init__(
            [class_obj["id"] for class_obj in wb_classes._class_set]
        )
        self.classes_obj_ref = wb_classes

    def to_dict(self, artifact=None):
        cl_dict = super(_WBClassesIdType, self).to_dict(artifact)
        # TODO (tss): Refactor this block with the similar one in wandb.Image.
        # This is a bit of a smell that the classes object does not follow
        # the same file-pattern as other media types.
        if artifact is not None:
            class_name = os.path.join("media", "cls")
            classes_entry = artifact.add(self.classes_obj_ref, class_name)
            cl_dict["schema"]["classes"] = {
                "type": "classes-file",
                "path": classes_entry.path,
                "digest": classes_entry.digest,  # is this needed really?
            }
        else:
            cl_dict["schema"]["classes"] = self.classes_obj_ref.to_json(artifact)
        return cl_dict

    @classmethod
    def from_dict(cls, json_dict, artifact=None):
        new_type = super(_WBAllowableType, _WBClassesIdType).from_dict(
            json_dict, artifact=None
        )
        assert type(new_type) == _WBClassesIdType
        if artifact is not None and "path" in json_dict["schema"]["classes"]:
            new_type.classes_obj_ref = artifact.get(
                json_dict["schema"]["classes"]["path"]
            )
        else:
            new_type.classes_obj_ref = Classes.from_json(
                json_dict["schema"]["classes"], artifact
            )
        return new_type


class _WBImageType(_WBType):
    name = "wandb.Image"

    def __init__(self, wb_image=None):
        assert wb_image is None or wb_image.__class__ == Image
        super(_WBImageType, self).__init__(wb_image)
        # It would be nice to use the dict type here, but this is a special case
        # where we only care about the first-level keys of a few fields.
        self.schema.update(
            {
                "box_keys": set(
                    list(wb_image._boxes.keys()) if wb_image and wb_image._boxes else []
                ),
                "mask_keys": set(
                    list(wb_image._masks.keys()) if wb_image and wb_image._masks else []
                ),
            }
        )

    def type_by_assignment(self, py_obj=None, wb_type=None):
        other_type = super(_WBImageType, self).type_by_assignment(py_obj, wb_type)
        if other_type is not None and (
            self.schema["box_keys"] == other_type.schema["box_keys"]
            and self.schema["mask_keys"] == other_type.schema["mask_keys"]
        ):
            return self
        else:
            return None


class _WBTableType(_WBType):
    name = "wandb.Table"

    def __init__(self, wb_table=None):
        assert wb_table is None or wb_table.__class__ == Table
        super(_WBTableType, self).__init__(wb_table)
        self.schema.update(
            {
                "column_types": wb_table._column_types
                if wb_table and wb_table._column_types
                else _WBDictType({}),
            }
        )

    def type_by_assignment(self, py_obj=None, wb_type=None):
        other_type = super(_WBTableType, self).type_by_assignment(py_obj, wb_type)
        new_table_type = None
        if other_type is not None:
            combined_column_types = self.schema["column_types"].type_by_assignment(
                None, other_type.schema["column_types"]
            )
            if combined_column_types is not None:
                new_table_type = _WBTableType()
                new_table_type.schema["column_types"] = combined_column_types

        return new_table_type


_WBType.register_type(_WBType)
_WBType.register_type(_WBTextType)
_WBType.register_type(_WBNumberType)
_WBType.register_type(_WBBooleanType)
_WBType.register_type(_WBObjectType)
_WBType.register_type(_WBListType)
_WBType.register_type(_WBDictType)
_WBType.register_type(_WBAllowableType)
_WBType.register_type(_WBClassesIdType)
_WBType.register_type(_WBImageType)
_WBType.register_type(_WBTableType)