import typing
import pydantic

from urllib import parse


class RunMoment(pydantic.BaseModel):
    """A moment in time in a run."""

    run: str  # run name

    # only step for now, in future this will be relaxed to be any metric
    metric: typing.Literal["_step"]

    # currently, the _step value to fork from. in future, this will be optional
    value: typing.Union[int, float]

    @classmethod
    def from_uri(cls, uri: str) -> "RunMoment":
        """Create a RunMoment from a URI."""

        parsable = "runmoment://" + uri
        parse_err = ValueError(
            f"Could not parse passed run moment string '{uri}', "
            f"expected format '<run>?<metric>=<value>'. "
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
        else:
            metric = list(query.keys())[0]
            if metric != "_step":
                raise parse_err
            value = query[metric][0]
        return cls(run=run, metric=metric, value=value)
