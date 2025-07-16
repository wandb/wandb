from typing import Any

from rich.style import Style

# Style presets
YELLOW = Style(color="yellow")
RED = Style(color="red")
GREEN = Style(color="green")
BRIGHT_RED = Style(color="bright_red")
BRIGHT_GREEN = Style(color="bright_green")
BLUE = Style(color="blue")
CYAN = Style(color="cyan")

DIM = Style(dim=True)
BOLD = Style(bold=True)


RED_DIM = Style.chain(RED, DIM)
GREEN_DIM = Style.chain(GREEN, DIM)
BOLD_BLUE = Style.chain(BLUE, BOLD)

# types
type ColName = str

# ------------------------------------------------------------------
# Cell formatting helpers
# ------------------------------------------------------------------


def format_cell(value: Any) -> str:
    """Format a cell value for prettier display in data tables."""
    import math

    # Empty for null / None / NaN
    if value is None:
        return ""

    if isinstance(value, float):
        if math.isnan(value):
            return ""
        # Use comma separators and show up to 3 decimal places (strip zeros)
        # Strip trailing zeros and optional decimal point
        return f"{value:,.3f}".rstrip("0").rstrip(".")

    if isinstance(value, int):
        return f"{value:,}"

    return str(value)


def style_diff_frac(diff_frac: int | float) -> Style:
    return Style.chain(
        "gray" if diff_frac == 0 else (GREEN if diff_frac > 0 else RED),
        BOLD if abs(diff_frac) > 0.05 else DIM,
    )
