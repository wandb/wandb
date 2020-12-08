"""
Wandb has special data types for logging rich visualizations.

All of the special data types are subclasses of WBValue. All of the data types
serialize to JSON, since that is what wandb uses to save the objects locally
and upload them to the W&B server.
"""
import sys

# This file is kept so that users can still :
# `import wandb.data_types`
# `from wandb import data_types`
#
# After Py2 is dropped, we can pull all of this back to top level.

PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.interface.data_types import *
else:
    from wandb.sdk_py27.interface.data_types import *
