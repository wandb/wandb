#!/usr/bin/env python
"""Finite state machine.

Simple FSM implementation.

Usage:
    ```python
    class A:
        def run(self) -> None:
            pass

    class B:
        def run(self) -> None:
            pass

    def to_b() -> bool:
        return True

    def to_a() -> bool:
        return True

    f = Fsm(states=[A(), B()],
            table={A: [(to_b, B)],
                   B: [(to_a, A)]})
    f.run()
    ```
"""

import sys
from abc import abstractmethod
from typing import Dict, Generic, Iterable, Tuple, Type, TypeVar

if sys.version_info >= (3, 8):
    from typing import Protocol
else:
    from typing_extensions import Protocol

if sys.version_info >= (3, 10):
    from typing import TypeAlias
else:
    from typing_extensions import TypeAlias

T_FsmData = TypeVar("T_FsmData", contravariant=True)


class FsmState(Protocol[T_FsmData]):
    @abstractmethod
    def run(self, data: T_FsmData) -> None:
        ...


class FsmCondition(Protocol[T_FsmData]):
    def __call__(self, data: T_FsmData) -> bool:
        ...


FsmTable: TypeAlias = Dict[
    Type[FsmState[T_FsmData]],
    Iterable[Tuple[FsmCondition[T_FsmData], Type[FsmState[T_FsmData]]]],
]


class Fsm(Generic[T_FsmData]):
    def __init__(self, states: Iterable[FsmState], table: FsmTable) -> None:
        pass

    def run(self, data: T_FsmData) -> None:
        pass
