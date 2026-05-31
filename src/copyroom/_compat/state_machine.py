"""Lightweight state machine with validated transitions.

Maps to the StateMachine helper described in §10.1 of the implementation plan.
Used by all lifecycle entities (CLISession, ProjectCreation, TemplateUpdate, etc.)
"""

from __future__ import annotations

from typing import TypeVar

S = TypeVar("S")


class InvalidTransitionError(Exception):
    """Raised when an entity attempts an invalid state transition."""

    def __init__(self, entity_name: str, from_state: S, to_state: S) -> None:
        self.entity_name = entity_name
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid {entity_name} transition: {from_state} -> {to_state}",
        )


class StateMachine[S]:
    """Lightweight state machine with validated transitions.

    Usage::

        sm = StateMachine(transitions, entity_name="ProjectCreation")
        sm.transition(entity, CreationStatus.initiated, CreationStatus.target_verified)
    """

    def __init__(self, transitions: dict[S, set[S]], entity_name: str = "Entity") -> None:
        self._transitions = transitions
        self._entity_name = entity_name

    def transition(self, from_state: S, to_state: S) -> S:
        """Validate and return the target state.

        Raises ``InvalidTransitionError`` if the transition is not declared.
        """
        valid = self._transitions.get(from_state, set())
        if to_state not in valid:
            raise InvalidTransitionError(self._entity_name, from_state, to_state)
        return to_state

    def can_transition(self, from_state: S, to_state: S) -> bool:
        """Return ``True`` if the transition is valid."""
        return to_state in self._transitions.get(from_state, set())

    def is_terminal(self, state: S) -> bool:
        """Return ``True`` if *state* has no outbound transitions."""
        return len(self._transitions.get(state, set())) == 0
