# Modifications made

This package has modifications made by the W&B team needed to fully implement Orjson into the W&B SDK.
Changes include:

- Added `OPT_FAIL_ON_INVALID_FLOAT`, which causes the library to raise an error when trying to serialize invalid floating point values (`NaN`, `Infinity`, `-Infinity`). Previously, these values were automatically converted to `null`/`None`.
