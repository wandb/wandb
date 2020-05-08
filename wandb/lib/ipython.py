def _get_python_type():
    try:
        if 'terminal' in get_ipython().__module__:
            return 'ipython'
        else:
            return 'jupyter'
    except (NameError, AttributeError):
        return "python"
