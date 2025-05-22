from typing import Sequence, Union

Number = Union[int, float]


def aggregate_mean(samples: Sequence[Number], precision: int = 2) -> float:
    return round(sum(samples) / len(samples), precision)


def aggregate_last(samples: Sequence[Number], precision: int = 2) -> Union[float, int]:
    if isinstance(samples[-1], int):
        return samples[-1]
    return round(samples[-1], precision)


def aggregate_max(samples: Sequence[Number], precision: int = 2) -> Union[float, int]:
    if isinstance(samples[-1], int):
        return max(samples)
    return round(max(samples), precision)


def aggregate_min(samples: Sequence[Number], precision: int = 2) -> Union[float, int]:
    if isinstance(samples[-1], int):
        return min(samples)
    return round(min(samples), precision)


def aggregate_sum(samples: Sequence[Number], precision: int = 2) -> Union[float, int]:
    if isinstance(samples[-1], int):
        return sum(samples)
    return round(sum(samples), precision)
