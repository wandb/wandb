#
"""
runid util.
"""

from typing import cast

import shortuuid  # type: ignore


def generate_id() -> str:
    # ~3t run ids (36**8)
    run_gen = shortuuid.ShortUUID(alphabet=list("0123456789abcdefghijklmnopqrstuvwxyz"))
    return cast(str, run_gen.random(8))
