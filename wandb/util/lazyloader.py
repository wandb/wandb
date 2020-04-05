# -*- coding: utf-8 -*-
"""
module lazyloader
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import types
import sys
import importlib

class LazyLoader(types.ModuleType):
    """Lazily import a module, mainly to avoid pulling in large dependencies.
    we use this for tensorflow and other optional libraries primarily at the top module level
    """

    # The lint error here is incorrect.
    def __init__(self, local_name, parent_module_globals, name, warning=None):  # pylint: disable=super-on-old-class
        self._local_name = local_name
        self._parent_module_globals = parent_module_globals
        self._warning = warning

        super(LazyLoader, self).__init__(str(name))

    def _load(self):
        """Load the module and insert it into the parent's globals."""
        # Import the target module and insert it into the parent's namespace
        module = importlib.import_module(self.__name__)
        self._parent_module_globals[self._local_name] = module
        # print("import", self.__name__)
        # print("Set global", self._local_name)
        # print("mod", module)
        sys.modules[self._local_name] = module

        # Emit a warning if one was specified
        if self._warning:
            print(self._warning)
            # Make sure to only warn once.
            self._warning = None

        # Update this object's dict so that if someone keeps a reference to the
        #   LazyLoader, lookups are efficient (__getattr__ is only called on lookups
        #   that fail).
        self.__dict__.update(module.__dict__)

        return module

    # def __getattribute__(self, item):
    #     print("getattribute", item)

    def __getattr__(self, item):
        # print("getattr", item)
        module = self._load()
        return getattr(module, item)

    def __dir__(self):
        # print("dir")
        module = self._load()
        return dir(module)
