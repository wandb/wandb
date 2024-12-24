#!/usr/bin/env python
"""Finite state machine.

Simple FSM implementation.

Usage:
    ```python
    class A:
        def on_output(self, inputs) -> None:
            pass


    class B:
        def on_output(self, inputs) -> None:
            pass


    def to_b(inputs) -> bool:
        return True


    def to_a(inputs) -> bool:
        return True


    f = Fsm(states=[A(), B()], table={A: [(to_b, B)], B: [(to_a, A)]})
    f.run({"input1": 1, "input2": 2})
    ```
"""

import sys
from abc import abstractmethod
from dataclasses import dataclass
from typing import (
    Callable,
    Dict,
    Generic,
    Optional,
    Protocol,
    Sequence,
    Type,
    TypeVar,
    Union,
    runtime_checkable,
)

if sys.version_info >= (3, 10):
    from typing import TypeAlias
else:
    from typing_extensions import TypeAlias

T_FsmInputs = TypeVar("T_FsmInputs", contravariant=True)
T_FsmContext = TypeVar("T_FsmContext")
T_FsmContext_cov = TypeVar("T_FsmContext_cov", covariant=True)
T_FsmContext_contra = TypeVar("T_FsmContext_contra", contravariant=True)


@runtime_checkable
class FsmStateCheck(Protocol[T_FsmInputs]):
    @abstractmethod
    def on_check(self, inputs: T_FsmInputs) -> None: ...  # pragma: no cover


@runtime_checkable
class FsmStateOutput(Protocol[T_FsmInputs]):
    @abstractmethod
    def on_state(self, inputs: T_FsmInputs) -> None: ...  # pragma: no cover


@runtime_checkable
class FsmStateEnter(Protocol[T_FsmInputs]):
    @abstractmethod
    def on_enter(self, inputs: T_FsmInputs) -> None: ...  # pragma: no cover


@runtime_checkable
class FsmStateEnterWithContext(Protocol[T_FsmInputs, T_FsmContext_contra]):
    @abstractmethod
    def on_enter(
        self, inputs: T_FsmInputs, context: T_FsmContext_contra
    ) -> None: ...  # pragma: no cover


@runtime_checkable
class FsmStateStay(Protocol[T_FsmInputs]):
    @abstractmethod
    def on_stay(self, inputs: T_FsmInputs) -> None: ...  # pragma: no cover


@runtime_checkable
class FsmStateExit(Protocol[T_FsmInputs, T_FsmContext_cov]):
    @abstractmethod
    def on_exit(self, inputs: T_FsmInputs) -> T_FsmContext_cov: ...  # pragma: no cover


# It would be nice if python provided optional protocol members, but it does not as described here:
#   https://peps.python.org/pep-0544/#support-optional-protocol-members
# Until then, we can only enforce that a state at least supports one protocol interface.  This
# unfortunately will not check the signature of other potential protocols.
FsmState: TypeAlias = Union[
    FsmStateCheck[T_FsmInputs],
    FsmStateOutput[T_FsmInputs],
    FsmStateEnter[T_FsmInputs],
    FsmStateEnterWithContext[T_FsmInputs, T_FsmContext],
    FsmStateStay[T_FsmInputs],
    FsmStateExit[T_FsmInputs, T_FsmContext],
]


@dataclass
class FsmEntry(Generic[T_FsmInputs, T_FsmContext]):
    condition: Callable[[T_FsmInputs], bool]
    target_state: Type[FsmState[T_FsmInputs, T_FsmContext]]
    action: Optional[Callable[[T_FsmInputs], None]] = None


FsmTableWithContext: TypeAlias = Dict[
    Type[FsmState[T_FsmInputs, T_FsmContext]],
    Sequence[FsmEntry[T_FsmInputs, T_FsmContext]],
]


FsmTable: TypeAlias = FsmTableWithContext[T_FsmInputs, None]


class FsmWithContext(Generic[T_FsmInputs, T_FsmContext]):
    _state_dict: Dict[Type[FsmState], FsmState]
    _table: FsmTableWithContext[T_FsmInputs, T_FsmContext]
    _state: FsmState[T_FsmInputs, T_FsmContext]
    _states: Sequence[FsmState]

    def __init__(
        self,
        states: Sequence[FsmState],
        table: FsmTableWithContext[T_FsmInputs, T_FsmContext],
    ) -> None:
        self._states = states
        self._table = table
        self._state_dict = {type(s): s for s in states}
        self._state = self._state_dict[type(states[0])]

    def _transition(
        self,
        inputs: T_FsmInputs,
        new_state: Type[FsmState[T_FsmInputs, T_FsmContext]],
        action: Optional[Callable[[T_FsmInputs], None]],
    ) -> None:
        if action:
            action(inputs)

        context = None
        if isinstance(self._state, FsmStateExit):
            context = self._state.on_exit(inputs)

        prev_state = type(self._state)
        if prev_state == new_state:
            if isinstance(self._state, FsmStateStay):
                self._state.on_stay(inputs)
        else:
            self._state = self._state_dict[new_state]
            if context and isinstance(self._state, FsmStateEnterWithContext):
                self._state.on_enter(inputs, context=context)
            elif isinstance(self._state, FsmStateEnter):
                self._state.on_enter(inputs)

    def _check_transitions(self, inputs: T_FsmInputs) -> None:
        for entry in self._table[type(self._state)]:
            if entry.condition(inputs):
                self._transition(inputs, entry.target_state, entry.action)
                return

    def input(self, inputs: T_FsmInputs) -> None:
        if isinstance(self._state, FsmStateCheck):
            self._state.on_check(inputs)
        self._check_transitions(inputs)
        if isinstance(self._state, FsmStateOutput):
            self._state.on_state(inputs)


Fsm: TypeAlias = FsmWithContext[T_FsmInputs, None]
