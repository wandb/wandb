"""
Utilities for parsing a test specification.


"""

import ast
import yaml


def load_docstring(filepath):
    file_contents = ""
    with open(filepath) as fd:
        file_contents = fd.read()
    module = ast.parse(file_contents)
    docstring = ast.get_docstring(module)
    if docstring is None:
        docstring = ""
    return docstring


# From: github.com/marshmallow-code/apispec
def load_yaml_from_docstring(docstring):
    """Loads YAML from docstring."""
    split_lines = docstring.split("\n")

    # Cut YAML from rest of docstring
    for index, line in enumerate(split_lines):
        line = line.strip()
        if line.startswith("---"):
            cut_from = index
            break
    else:
        return None

    yaml_string = "\n".join(split_lines[cut_from:])
    return yaml.load(yaml_string, Loader=yaml.SafeLoader)
