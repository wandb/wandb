META_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["boolean", "integer", "number", "string", "object", "array"],
        },
        "title": {"type": "string"},
        "description": {"type": "string"},
        "format": {"type": "string"},
        "enum": {"type": "array", "items": {"type": ["integer", "number", "string"]}},
        "properties": {"type": "object", "patternProperties": {".*": {"$ref": "#"}}},
        "allOf": {"type": "array", "items": {"$ref": "#"}},
        # Array-specific properties
        "items": {"$ref": "#"},
        "uniqueItems": {"type": "boolean"},
        "minItems": {"type": "integer", "minimum": 0},
        "maxItems": {"type": "integer", "minimum": 0},
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
        {
            "if": {"properties": {"type": {"const": "array"}}},
            "then": {
                "required": ["items"],
                "properties": {
                    "items": {
                        "properties": {
                            "type": {"enum": ["integer", "number", "string"]},
                            "enum": {
                                "type": "array",
                                "items": {"type": ["integer", "number", "string"]},
                            },
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "format": {"type": "string"},
                        },
                        "required": ["type", "enum"],
                        "unevaluatedProperties": False,
                    },
                    "uniqueItems": {"type": "boolean"},
                    "minItems": {"type": "integer", "minimum": 0},
                    "maxItems": {"type": "integer", "minimum": 0},
                },
            },
        },
    ],
    "unevaluatedProperties": False,
}
