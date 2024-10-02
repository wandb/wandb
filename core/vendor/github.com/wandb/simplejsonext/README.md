# Simple extended JSON parser

This is a simple library open-source code for extended-JSON parsing. It
understands (and emits) JSON containing `Infinity` and `NaN` numbers as unquoted
tokens (an extension shared by Python's `json` library, among others) and it
only decodes simply typed values. It (currently) does not know how to decode
JSON into structs and their fields, but rather all JSON {objects} become
`map[string]any`, all JSON [arrays] become `[]any`, and all JSON values are
represented within `any` values. (`any` in golang is synonymous with and
shorthand for `interface{}`, a dynamically typed value type with no constraints
and no guaranteed interface.)
