"""Lightweight user-feedback capture wired into the hash-chained audit ledger.

A thumbs up/down plus a free-text correction is appended as a
``user_feedback`` ledger entry via :meth:`AuditLedger.log`, so feedback
inherits the ledger's tamper evidence and is verifiable with
:meth:`AuditLedger.verify_chain` alongside every other event.
"""
from __future__ import annotations

from typing import Dict, List

from .audit import AuditLedger

EVENT = "user_feedback"
ACTOR = "user"
RATINGS = ("up", "down")


class FeedbackError(ValueError):
    """Raised when a feedback submission is malformed."""


def _require_nonblank(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FeedbackError(f"{name} must be a non-blank string")
    return value.strip()


def capture_feedback(ledger: AuditLedger, *, session_id: str, turn_id: str,
                     rating: str, correction: str = "") -> Dict:
    """Append one feedback event to the audit ledger; returns the entry.

    ``rating`` must be ``"up"`` or ``"down"``. A ``"down"`` rating requires
    a non-blank ``correction`` describing what was wrong; an ``"up"`` rating
    may omit it. ``session_id`` / ``turn_id`` link the feedback to the
    conversation turn it refers to (supplied by the calling UI/orchestrator).
    """
    session_id = _require_nonblank("session_id", session_id)
    turn_id = _require_nonblank("turn_id", turn_id)
    if rating not in RATINGS:
        raise FeedbackError(
            f"rating must be one of {RATINGS}, got {rating!r}")
    correction = correction.strip() if isinstance(correction, str) else ""
    if rating == "down" and not correction:
        raise FeedbackError("a thumbs-down requires a non-blank correction")
    details = {
        "session_id": session_id,
        "turn_id": turn_id,
        "rating": rating,
        "correction": correction,
    }
    return ledger.log(EVENT, ACTOR, details)


def list_feedback(ledger: AuditLedger) -> List[Dict]:
    """Return all feedback entries currently in the ledger, in order."""
    return [e for e in ledger.entries if e["event"] == EVENT]
