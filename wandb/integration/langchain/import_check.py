"""
This file performs a runtime check to see if the langchain package is installed.
This way it can be imported before any langchain imports in order to give a
more helpful error message if langchain is not installed.
"""

from typing import Any


def import_langchain() -> Any:
    try:
        import langchain
    except ImportError:
        raise ImportError(
            "To use the LangChain WandbTracer you need to have the `langchain` python "
            "package installed. Please install it with `pip install langchain`"
        )
    return langchain


langchain = import_langchain()
