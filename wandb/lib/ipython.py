def _get_python_type():
    try:
        from IPython import get_ipython
    except ImportError:
        return 'python'
    if get_ipython() is None:
        return "python"
    elif 'terminal' in get_ipython().__module__:
        return 'ipython'
    else:
        return 'jupyter'
