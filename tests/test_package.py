import importlib
import sys
import wandb


def a():
    pass


class_type = type
fn_type = type(a)


def assertWBPublicObject(submodule_path=None, name=None, obj_type=None, wb_alias=None):
    package_name = "wandb"

    module_name = package_name
    if type(submodule_path) == str and len(submodule_path) > 0:
        module_name += "." + submodule_path

    module = importlib.import_module(module_name)

    if type(name) is str and len(name) > 0:
        assert hasattr(module, name)
        obj = getattr(module, name)
    else:
        obj = module

    if obj_type is not None:
        assert type(obj) == obj_type

    if type(wb_alias) is str and len(wb_alias) > 0:
        assert hasattr(wandb, wb_alias)
        alias_obj = getattr(wandb, wb_alias)
        print(alias_obj, obj)
        assert alias_obj == obj


assertWBPublicObject("", "__version__", str)

## Validate the Data Types
assertWBPublicObject("data_types", "Graph", class_type, "Graph")
assertWBPublicObject("data_types", "Image", class_type, "Image")
assertWBPublicObject("data_types", "Plotly", class_type, "Plotly")
assertWBPublicObject("data_types", "Video", class_type, "Video")
assertWBPublicObject("data_types", "Audio", class_type, "Audio")
assertWBPublicObject("data_types", "Table", class_type, "Table")
assertWBPublicObject("data_types", "Html", class_type, "Html")
assertWBPublicObject("data_types", "Object3D", class_type, "Object3D")
assertWBPublicObject("data_types", "Molecule", class_type, "Molecule")
assertWBPublicObject("data_types", "Histogram", class_type, "Histogram")
assertWBPublicObject("data_types", "Classes", class_type, "Classes")
assertWBPublicObject("data_types", "JoinedTable", class_type, "JoinedTable")

PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    assertWBPublicObject("sdk.lib", None, None, "wandb_lib")
    assertWBPublicObject("sdk", None, None, "wandb_sdk")
    assertWBPublicObject("sdk", "init", fn_type, "init")
    assertWBPublicObject("sdk", "setup", fn_type, "setup")
    assertWBPublicObject("sdk", "save", fn_type, "save")
    assertWBPublicObject("sdk", "watch", fn_type, "watch")
    assertWBPublicObject("sdk", "unwatch", fn_type, "unwatch")
    assertWBPublicObject("sdk", "finish", fn_type, "join")
    assertWBPublicObject("sdk", "login", fn_type, "login")
    assertWBPublicObject("sdk", "helper", fn_type, "helper")
    assertWBPublicObject("sdk", "Artifact", class_type, "Artifact")
    assertWBPublicObject("sdk", "AlertLevel", class_type, "AlertLevel")
    assertWBPublicObject("sdk", "Settings", class_type, "Settings")
    assertWBPublicObject("sdk", "Config", class_type, "Config")
else:
    assertWBPublicObject("sdk_py27.lib", None, None, "wandb_lib")
    assertWBPublicObject("sdk_py27", None, None, "wandb_sdk")
    assertWBPublicObject("sdk_py27", "init", fn_type, "init")
    assertWBPublicObject("sdk_py27", "setup", fn_type, "setup")
    assertWBPublicObject("sdk_py27", "save", fn_type, "save")
    assertWBPublicObject("sdk_py27", "watch", fn_type, "watch")
    assertWBPublicObject("sdk_py27", "unwatch", fn_type, "unwatch")
    assertWBPublicObject("sdk_py27", "finish", fn_type, "join")
    assertWBPublicObject("sdk_py27", "login", fn_type, "login")
    assertWBPublicObject("sdk_py27", "helper", fn_type, "helper")
    assertWBPublicObject("sdk_py27", "Artifact", class_type, "Artifact")
    assertWBPublicObject("sdk_py27", "AlertLevel", class_type, "AlertLevel")
    assertWBPublicObject("sdk_py27", "Settings", class_type, "Settings")
    assertWBPublicObject("sdk_py27", "Config", class_type, "Config")
