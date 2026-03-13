try:
    import cwsandbox
except ImportError:
    raise ImportError(
        "cwsandbox is not installed. Please install it with: pip install wandb[sandbox]"
    )

# if TYPE_CHECKING

from cwsandbox import Sandbox
