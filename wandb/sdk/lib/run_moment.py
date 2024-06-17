import sys
from dataclasses import dataclass
from typing import Union, cast
from urllib import parse

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

_STEP = Literal["_step"]


@dataclass
class RunMoment:
    """A moment in a run."""

    run: str  # run name

    # currently, the _step value to fork from. in future, this will be optional
    value: Union[int, float]

    # only step for now, in future this will be relaxed to be any metric
    metric: _STEP = "_step"

    def __post_init__(self):
        if self.metric != "_step":
            raise ValueError(
                f"Only the metric '_step' is supported, got '{self.metric}'."
            )
        if not isinstance(self.value, (int, float)):
            raise ValueError(
                f"Only int or float values are supported, got '{self.value}'."
            )
        if not isinstance(self.run, str):
            raise ValueError(f"Only string run names are supported, got '{self.run}'.")

    @classmethod
    def from_uri(cls, uri: str) -> "RunMoment":
        parsable = "runmoment://" + uri
        parse_err = ValueError(
            f"Could not parse passed run moment string '{uri}', "
            f"expected format '<run>?<metric>=<numeric_value>'. "
            f"Currently, only the metric '_step' is supported. "
            f"Example: 'ans3bsax?_step=123'."
        )

        try:
            parsed = parse.urlparse(parsable)
        except ValueError as e:
            raise parse_err from e

        if parsed.scheme != "runmoment":
            raise parse_err

        # extract run, metric, value from parsed
        if not parsed.netloc:
            raise parse_err

        run = parsed.netloc

        if parsed.path or parsed.params or parsed.fragment:
            raise parse_err

        query = parse.parse_qs(parsed.query)
        if len(query) != 1:
            raise parse_err

        metric = list(query.keys())[0]
        if metric != "_step":
            raise parse_err
        value: str = query[metric][0]
        try:
            num_value = int(value) if value.isdigit() else float(value)
        except ValueError as e:
            raise parse_err from e

        return cls(run=run, metric=cast(_STEP, metric), value=num_value)
