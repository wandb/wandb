__all__ = ("autolog", "WandbLogger")

try:
    import openai
except Exception:
    print(
        "Error: `openai` not installed >> This integration requires openai!  To fix, please `pip install openai`"
    )

from pkg_resources import parse_version
from .openai import autolog

if parse_version(openai.__version__) > parse_version("0.28.1"):
    from .fine_tune import WandbLogger
