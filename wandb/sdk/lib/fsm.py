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
from typing import Dict, Generic, Sequence, Tuple, Type, TypeVar, Union

if sys.version_info >= (3, 8):
    from typing import Protocol, runtime_checkable
else:
    from typing_extensions import Protocol, runtime_checkable

if sys.version_info >= (3, 10):
    from typing import TypeAlias
else:
    from typing_extensions import TypeAlias

T_FsmData = TypeVar("T_FsmData", contravariant=True)


@runtime_checkable
class FsmStateRun(Protocol[T_FsmData]):
    @abstractmethod
    def run(self, data: T_FsmData) -> None:
        ...


@runtime_checkable
class FsmStateEnter(Protocol[T_FsmData]):
    @abstractmethod
    def enter(self, data: T_FsmData) -> None:
        ...


@runtime_checkable
class FsmStateExit(Protocol[T_FsmData]):
    @abstractmethod
    def exit(self, data: T_FsmData) -> None:
        ...


FsmState: TypeAlias = Union[
    FsmStateRun[T_FsmData], FsmStateEnter[T_FsmData], FsmStateExit[T_FsmData]
]


class FsmCondition(Protocol[T_FsmData]):
    def __call__(self, data: T_FsmData) -> bool:
        ...


FsmTable: TypeAlias = Dict[
    Type[FsmState[T_FsmData]],
    Sequence[Tuple[FsmCondition[T_FsmData], Type[FsmState[T_FsmData]]]],
]


class Fsm(Generic[T_FsmData]):
    _state_dict: Dict[Type[FsmState], FsmState]
    _table: FsmTable[T_FsmData]
    _state: FsmState[T_FsmData]

    def __init__(self, states: Sequence[FsmState], table: FsmTable[T_FsmData]) -> None:
        self._state_dict = {type(s): s for s in states}
        self._table = table
        self._state = self._state_dict[type(states[0])]

    def _transition(
        self, data: T_FsmData, new_state: Type[FsmState[T_FsmData]]
    ) -> None:
        if isinstance(self._state, FsmStateEnter):
            self._state.enter(data)

        self._state = self._state_dict[new_state]

        if isinstance(self._state, FsmStateExit):
            self._state.exit(data)

    def _check_transitions(self, data: T_FsmData) -> None:
        for cond, new_state in self._table[type(self._state)]:
            if cond(data):
                self._transition(data, new_state)
                return

    def run(self, data: T_FsmData) -> None:
        self._check_transitions(data)
        if isinstance(self._state, FsmStateRun):
            self._state.run(data)
