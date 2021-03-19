from .local import LocalAgent
from .ngc import NGCAgent


def agent_class(name: str):
    if name == "ngc":
        return NGCAgent
    else:
        return LocalAgent
