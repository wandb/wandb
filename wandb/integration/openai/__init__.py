__all__ = ("autolog", "WandbLogger")

try:
    import openai
except Exception:
    print(
        "Error: `openai` not installed >> This integration requires openai!  To fix, please `pip install openai`"
    )

from pkg_resources import parse_version

openai_version = openai.__version__
if parse_version(openai_version) <= parse_version("0.28.1"):
    from .openai import autolog
else:
    from .fine_tune import WandbLogger
    from .openai import autolog
