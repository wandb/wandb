# lifted from github.com/wandb/sweeps

import json
import jsonschema
from jsonschema import Draft7Validator, validators

from pathlib import Path

testlib_config_jsonschema_fname = Path(__file__).parent / "schema-wandb-testlib.json"
with open(testlib_config_jsonschema_fname, "r") as f:
    testlib_config_jsonschema = json.load(f)


format_checker = jsonschema.FormatChecker()


@format_checker.checks("float")
def float_checker(value):
    return isinstance(value, float)


@format_checker.checks("integer")
def int_checker(value):
    return isinstance(value, int)


validator = Draft7Validator(
    schema=testlib_config_jsonschema, format_checker=format_checker
)


def extend_with_default(validator_class):
    # https://python-jsonschema.readthedocs.io/en/stable/faq/#why-doesn-t-my-schema-s-default-property-set-the-default-on-my-instance
    validate_properties = validator_class.VALIDATORS["properties"]

    def set_defaults(validator, properties, instance, schema):

        errored = False
        for error in validate_properties(validator, properties, instance, schema,):
            errored = True
            yield error

        if not errored:
            for property, subschema in properties.items():
                if "default" in subschema:
                    instance.setdefault(property, subschema["default"])

    return validators.extend(validator_class, {"properties": set_defaults},)


DefaultFiller = extend_with_default(Draft7Validator)
default_filler = DefaultFiller(
    schema=testlib_config_jsonschema, format_checker=format_checker
)
