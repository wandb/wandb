import typing
import pydantic


class RunMoment(pydantic.BaseModel):
    """A moment in time in a run."""

    entity: str  # run entity
    project: str  # run project
    run: str  # run name

    # only step for now, in future this will be relaxed to be any metric
    metric: typing.Literal["_step"]

    # currently, the _step value to fork from. in future, this will be optional
    value: typing.Union[int, float]
