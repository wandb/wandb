This folder contains Python dependencies needed for development and CI.

For local development, use `uv pip install -r requirements/requirements_dev.txt`.

CI uses precompiled files for speed and reproducibility. Use `bash requirements/generate.sh` or see the top of each file for the command used to generate it.

The generator normally waits one week before accepting new releases. `certifi`
and `Pillow` bypass that delay so security patches can be picked up immediately.
Security version floors belong in `requirements_dev.txt` so they also apply to
local development installs. If another urgent fix is newer than the cutoff, add
a package exception in `generate.sh` before regenerating the files.
