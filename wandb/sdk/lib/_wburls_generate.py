from wburls import wburls  # type: ignore

template = """
import sys

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


URLS = Literal[
    $literal_list
]
"""


def generate() -> None:
    urls = wburls._get_urls()
    literal_list = ", ".join([f"{key!r}" for key in urls])
    print(template.replace("$literal_list", literal_list))


if __name__ == "__main__":
    generate()
