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

from wburls import wburls


def generate():
    urls = wburls._get_urls()
    literal_list = ", ".join([f'"{key}"' for key in urls])
    print(template.replace("$literal_list", literal_list))


if __name__ == "__main__":
    generate()
