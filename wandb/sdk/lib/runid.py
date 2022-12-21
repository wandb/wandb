"""
runid util.
"""

import shortuuid


def generate_id(length: int = 8) -> str:
    """Generate a random base-36 string of `length` digits."""
    # There are ~2.8T base-36 8-digit strings. If we generate 210k ids,
    # we'll have a ~1% chance of collision.
    run_gen = shortuuid.ShortUUID(alphabet="0123456789abcdefghijklmnopqrstuvwxyz")
    return run_gen.random(length)
