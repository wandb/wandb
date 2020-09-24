import wandb


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


def display_html(html):
    """Displays HTML in notebooks, is a noop outside of a jupyter context"""
    try:
        from IPython.core.display import display, HTML  # type: ignore
    except ImportError:
        wandb.termwarn("Unable to render HTML, can't import display from ipython.core")
        return False
    return display(HTML(html))


def display_widget(widget):
    """Displays ipywidgets in notebooks, is a noop outside of a jupyter context"""
    try:
        from IPython.core.display import display
    except ImportError:
        wandb.termwarn("Unable to render Widget, can't import display from ipython.core")
        return False
    return display(widget)


def jupyter_progress_bar(min=0, max=1):
    """Returns an ipywidget progress bar or None if we can't import it"""
    ipywidgets = wandb.util.get_module("ipywidgets")
    try:
        if ipywidgets is None:
            # TODO: this currently works in iPython but it's deprecated since 4.0
            from IPython.html.widgets import FloatProgress  # type: ignore
        else:
            FloatProgress = ipywidgets.FloatProgress  # noqa:N806
        return FloatProgress(min=min, max=max)
    except ImportError:
        return None
