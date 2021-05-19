from typing import List

from ...errors import term


def handle_sweep_config_violations(warnings):
    warning_base = (
        "Malformed sweep config detected! This may cause your sweep to behave in unexpected ways. "
        "To fix this, please address the sweep config schema violations below:\n\n"
    )
    for i, warning in enumerate(warnings):
        warning_base += "Violation {}. {}\n\n".format(i + 1, warning)
    term.termwarn(warning_base)
