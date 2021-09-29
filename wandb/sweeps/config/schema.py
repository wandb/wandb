import json
import jsonref
import jsonschema
from jsonschema import Draft7Validator, validators

from pathlib import Path
from typing import Dict, Optional, Tuple
from copy import deepcopy

sweep_config_jsonschema_fname = Path(__file__).parent / "schema.json"
with open(sweep_config_jsonschema_fname, "r") as f:
    sweep_config_jsonschema = json.load(f)


dereferenced_sweep_config_jsonschema = jsonref.JsonRef.replace_refs(
    sweep_config_jsonschema
)

format_checker = jsonschema.FormatChecker()


@format_checker.checks("float")
def float_checker(value):
    return isinstance(value, float)


@format_checker.checks("integer")
def int_checker(value):
    return isinstance(value, int)


validator = Draft7Validator(
    schema=sweep_config_jsonschema, format_checker=format_checker
)


def extend_with_default(validator_class):
    # https://python-jsonschema.readthedocs.io/en/stable/faq/#why-doesn-t-my-schema-s-default-property-set-the-default-on-my-instance
    validate_properties = validator_class.VALIDATORS["properties"]

    def set_defaults(validator, properties, instance, schema):

        errored = False
        for error in validate_properties(
            validator,
            properties,
            instance,
            schema,
        ):
            errored = True
            yield error

        if not errored:
            for property, subschema in properties.items():
                if "default" in subschema:
                    instance.setdefault(property, subschema["default"])

    return validators.extend(
        validator_class,
        {"properties": set_defaults},
    )


DefaultFiller = extend_with_default(Draft7Validator)
default_filler = DefaultFiller(
    schema=sweep_config_jsonschema, format_checker=format_checker
)


def fill_parameter(config: Dict) -> Optional[Tuple[str, Dict]]:
    # names of the parameter definitions that are allowed
    allowed_schemas = [
        d["$ref"].split("/")[-1]
        for d in sweep_config_jsonschema["definitions"]["parameter"]["anyOf"]
    ]

    for schema_name in allowed_schemas:
        # create a jsonschema object to validate against the subschema
        subschema = dereferenced_sweep_config_jsonschema["definitions"][schema_name]

        try:
            jsonschema.Draft7Validator(
                subschema, format_checker=format_checker
            ).validate(config)
        except jsonschema.ValidationError:
            continue
        else:
            filler = DefaultFiller(subschema, format_checker=format_checker)

            # this sets the defaults, modifying config inplace
            config = deepcopy(config)
            filler.validate(config)
            return schema_name, config

    return None


def fill_validate_metric(d: Dict) -> Dict:
    d = deepcopy(d)

    if "metric" in d:
        if "goal" in d["metric"]:
            if (
                d["metric"]["goal"]
                not in dereferenced_sweep_config_jsonschema["properties"]["metric"][
                    "properties"
                ]["goal"]["enum"]
            ):
                # let it be filled in by the schema default
                del d["metric"]["goal"]

        filler = DefaultFiller(
            schema=dereferenced_sweep_config_jsonschema["properties"]["metric"],
            format_checker=format_checker,
        )
        filler.validate(d["metric"])
    return d


def fill_validate_early_terminate(d: Dict) -> Dict:
    d = deepcopy(d)
    if d["early_terminate"]["type"] == "hyperband":
        filler = DefaultFiller(
            schema=dereferenced_sweep_config_jsonschema["definitions"][
                "hyperband_stopping"
            ],
            format_checker=format_checker,
        )
        filler.validate(d["early_terminate"])
    return d


def fill_validate_schema(d: Dict) -> Dict:
    from . import schema_violations_from_proposed_config

    # check that the schema is valid
    violations = schema_violations_from_proposed_config(d)
    if len(violations) != 0:
        raise jsonschema.ValidationError("\n".join(violations))

    validated = deepcopy(d)

    # update the parameters
    filled = {}
    for k, v in validated["parameters"].items():
        result = fill_parameter(v)
        if result is None:
            raise jsonschema.ValidationError(f"Parameter {k} is malformed")
        _, config = result
        filled[k] = config
    validated["parameters"] = filled

    if "early_terminate" in validated:
        validated = fill_validate_early_terminate(validated)

    return validated
