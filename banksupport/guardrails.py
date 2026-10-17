"""Confirmation gates for high-risk actions.

Checkbooks, address changes and credit-limit changes always require an
explicit user confirmation before the underlying tool runs. Large amounts
(above CONFIRM_THRESHOLD) require confirmation regardless of kind.
Nothing gated ever executes without a recorded confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Any, Dict, List, Optional


class GuardrailError(Exception):
    """Unknown action, or an action that is no longer pending."""


CONFIRM_THRESHOLD = 10000.00
ALWAYS_CONFIRM = {"checkbook", "address_change", "credit_limit"}


@dataclass
class PendingAction:
    action_id: str
    session_id: str
    kind: str
    description: str
    server: str
    tool: str
    tool_args: Dict[str, Any]
    permission: str
    amount: Optional[float] = None
    status: str = "pending"  # pending | confirmed | executed | cancelled


class ConfirmationGate:
    def __init__(self) -> None:
        self._actions: Dict[str, PendingAction] = {}
        self._counter = count(1)

    @staticmethod
    def needs_confirmation(kind: str, amount: Optional[float] = None) -> bool:
        if kind in ALWAYS_CONFIRM:
            return True
        return amount is not None and amount > CONFIRM_THRESHOLD

    def request(self, session_id: str, kind: str, description: str,
              server: str, tool: str, tool_args: Dict[str, Any],
              permission: str, amount: Optional[float] = None) -> str:
        action_id = f"act-{next(self._counter):04d}"
        self._actions[action_id] = PendingAction(
            action_id=action_id, session_id=session_id, kind=kind,
            description=description, server=server, tool=tool,
            tool_args=tool_args, permission=permission, amount=amount,
        )
        return action_id

    def get(self, action_id: str) -> PendingAction:
        try:
            return self._actions[action_id]
        except KeyError:
            raise GuardrailError(f"unknown action '{action_id}'")

    def pending_for(self, session_id: str) -> List[PendingAction]:
        return [a for a in self._actions.values()
                if a.session_id == session_id and a.status == "pending"]

    def confirm(self, action_id: str, approved: bool) -> PendingAction:
        action = self.get(action_id)
        if action.status != "pending":
            raise GuardrailError(f"action '{action_id}' is already {action.status}")
        action.status = "confirmed" if approved else "cancelled"
        return action

    def mark_executed(self, action_id: str) -> PendingAction:
        action = self.get(action_id)
        action.status = "executed"
        return action
