META_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["boolean", "integer", "number", "string", "object"],
        },
        "title": {"type": "string"},
        "description": {"type": "string"},
        "enum": {"type": "array", "items": {"type": ["integer", "number", "string"]}},
        "properties": {"type": "object", "patternProperties": {".*": {"$ref": "#"}}},
        "allOf": {"type": "array", "items": {"$ref": "#"}},
    },
    "allOf": [
        {
            "if": {"properties": {"type": {"const": "number"}}},
            "then": {
                "properties": {
                    "minimum": {"type": ["integer", "number"]},
                    "maximum": {"type": ["integer", "number"]},
                    "exclusiveMinimum": {"type": ["integer", "number"]},
                    "exclusiveMaximum": {"type": ["integer", "number"]},
                }
            },
        },
        {
            "if": {"properties": {"type": {"const": "integer"}}},
            "then": {
                "properties": {
                    "minimum": {"type": "integer"},
                    "maximum": {"type": "integer"},
                    "exclusiveMinimum": {"type": "integer"},
                    "exclusiveMaximum": {"type": "integer"},
                }
            },
        },
    ],
    "unevaluatedProperties": False,
}
