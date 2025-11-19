"""runid util."""

import random
import secrets
from string import ascii_lowercase, digits

_ID_CHARS = f"{ascii_lowercase}{digits}"


def generate_id(length: int = 8) -> str:
    """Generate a random base-36 string of `length` digits."""
    # There are ~2.8T base-36 8-digit strings. If we generate 210k ids,
    # we'll have a ~1% chance of collision.
    return "".join(secrets.choice(_ID_CHARS) for _ in range(length))


def generate_fast_id(length: int = 8) -> str:
    """Faster alternative to `generate_id` if cryptographic strength isn't needed.

    In local testing at the time of implementation, this is ~30-50x faster than
    `generate_id` when generating 128-character IDs.
    """
    return "".join(random.choices(_ID_CHARS, k=length))
