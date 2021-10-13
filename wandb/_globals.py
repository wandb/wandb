# WARNING: This is an anti-pattern file and we should avoid
# adding to it and remove entries whenever possible. This file
# contains global objects which need to be referenced by multiple
# submodules. If you need a global object, seriously reconsider. This
# file is intended to be a stop gap to help during code migrations (eg.
# when moving to typing a module) to avoid circular references. Anything
# added here is pure tech debt. Use with care. - Tim

_glob_datatypes_callback = None


def _datatypes_set_callback(cb):
    global _glob_datatypes_callback
    _glob_datatypes_callback = cb


def _datatypes_callback(fname):
    if _glob_datatypes_callback:
        _glob_datatypes_callback(fname)
