"""Lifecycle state-machine tests."""

import unittest

from magi.domain import DecisionState, InvalidStateTransition
from magi.orchestration import DecisionStateMachine
from tests.fixtures.factories import DECISION_ID


class DecisionStateMachineTests(unittest.TestCase):
    def test_happy_path_reaches_completed(self) -> None:
        machine = DecisionStateMachine(DECISION_ID)
        path = (
            DecisionState.NORMALIZED,
            DecisionState.WAITING_FOR_USER,
            DecisionState.EVIDENCE_READY,
            DecisionState.FIRST_BALLOT,
            DecisionState.CROSS_REVIEW,
            DecisionState.ARBITRATED,
            DecisionState.COMPLETED,
        )
        for state in path:
            machine.transition(state, reason=f"advance to {state.value}")
        self.assertEqual(machine.state, DecisionState.COMPLETED)
        self.assertTrue(machine.is_terminal)
        self.assertEqual(len(machine.history), len(path))

    def test_cannot_skip_user_confirmation(self) -> None:
        machine = DecisionStateMachine(DECISION_ID)
        machine.transition(DecisionState.NORMALIZED, reason="normalized")
        with self.assertRaises(InvalidStateTransition):
            machine.transition(DecisionState.EVIDENCE_READY, reason="skip confirmation")

    def test_terminal_state_cannot_transition(self) -> None:
        machine = DecisionStateMachine(DECISION_ID)
        machine.transition(DecisionState.CANCELLED, reason="user cancelled")
        with self.assertRaises(InvalidStateTransition):
            machine.transition(DecisionState.NORMALIZED, reason="resume")

    def test_transition_requires_reason(self) -> None:
        machine = DecisionStateMachine(DECISION_ID)
        with self.assertRaisesRegex(ValueError, "requires a reason"):
            machine.transition(DecisionState.NORMALIZED, reason=" ")


if __name__ == "__main__":
    unittest.main()

