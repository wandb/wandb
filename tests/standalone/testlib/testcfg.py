"""Base TestlibConfig classes."""

import yaml

from typing import Union, Dict, List

import jsonschema
from .schema import validator


def schema_violations_from_proposed_config(config: Dict) -> List[str]:

    schema_violation_messages = []
    for error in validator.iter_errors(config):
        schema_violation_messages.append(f"{error.message}")

    return schema_violation_messages


class TestlibConfig(dict):
    def __init__(self, d: Dict):
        super(TestlibConfig, self).__init__(d)

        if not isinstance(d, TestlibConfig):
            # ensure the data conform to the schema
            schema_violation_messages = schema_violations_from_proposed_config(d)

            if len(schema_violation_messages) > 0:
                err_msg = "\n".join(schema_violation_messages)
                raise jsonschema.ValidationError(err_msg)

    def __str__(self) -> str:
        return repr(self)

    def __repr__(self):
        return yaml.safe_dump(dict(self))
