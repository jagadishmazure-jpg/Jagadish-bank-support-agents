"""Feedback capture wired into the hash-chained audit ledger.

All synthetic/fictional data. Deterministic: no network, no keys.
"""
import pytest

from banksupport.audit import AuditLedger
from banksupport.feedback import (
    ACTOR,
    EVENT,
    FeedbackError,
    capture_feedback,
    list_feedback,
)


def make_ledger():
    ledger = AuditLedger()
    ledger.log("auth_decision", "system", {"tier": "standard"})
    return ledger


def test_thumbs_up_without_correction_appends():
    ledger = make_ledger()
    entry = capture_feedback(
        ledger, session_id="s1", turn_id="t1", rating="up")
    assert entry["event"] == EVENT
    assert entry["actor"] == ACTOR
    assert entry["details"]["session_id"] == "s1"
    assert entry["details"]["turn_id"] == "t1"
    assert entry["details"]["rating"] == "up"
    assert ledger.verify_chain()


def test_thumbs_down_with_correction_appends():
    ledger = make_ledger()
    entry = capture_feedback(
        ledger, session_id="s2", turn_id="t7", rating="down",
        correction="  cited the wrong account balance  ")
    assert entry["details"]["rating"] == "down"
    assert entry["details"]["correction"] == "cited the wrong account balance"
    assert ledger.verify_chain()


def test_thumbs_down_without_correction_rejected():
    ledger = make_ledger()
    with pytest.raises(FeedbackError):
        capture_feedback(ledger, session_id="s1", turn_id="t1", rating="down")


def test_whitespace_correction_rejected():
    ledger = make_ledger()
    with pytest.raises(FeedbackError):
        capture_feedback(
            ledger, session_id="s1", turn_id="t1", rating="down",
            correction="   ")


def test_out_of_range_rating_rejected():
    ledger = make_ledger()
    with pytest.raises(FeedbackError):
        capture_feedback(
            ledger, session_id="s1", turn_id="t1", rating="maybe",
            correction="x")


def test_blank_session_or_turn_rejected():
    ledger = make_ledger()
    with pytest.raises(FeedbackError):
        capture_feedback(ledger, session_id="  ", turn_id="t1", rating="up")
    with pytest.raises(FeedbackError):
        capture_feedback(ledger, session_id="s1", turn_id="", rating="up")
    assert ledger.verify_chain()


def test_interleaved_feedback_chain_verifies_and_lists_only_feedback():
    ledger = make_ledger()
    capture_feedback(ledger, session_id="s1", turn_id="t1", rating="up")
    ledger.log("confirmation", "agent", {"gate": "credit-limit"})
    capture_feedback(ledger, session_id="s1", turn_id="t2", rating="down",
                     correction="denial reason was unclear")
    assert ledger.verify_chain()
    fb = list_feedback(ledger)
    assert len(fb) == 2
    assert [e["details"]["turn_id"] for e in fb] == ["t1", "t2"]


def test_tampered_feedback_breaks_chain():
    ledger = make_ledger()
    capture_feedback(ledger, session_id="s1", turn_id="t1", rating="up")
    assert ledger.verify_chain()
    ledger.entries[-1]["details"]["rating"] = "down"
    assert not ledger.verify_chain()


def test_correction_pii_is_scrubbed_before_it_reaches_the_ledger():
    from banksupport.audit import AuditLedger
    from banksupport.feedback import capture_feedback

    ledger = AuditLedger()
    entry = capture_feedback(ledger, session_id="s1", turn_id="t1", rating="down",
                             correction="wrong card, mine is 4111 1111 1111 1111 and SSN 123-45-6789")
    text = str(ledger.entries)
    assert "4111" not in text and "123-45-6789" not in text
    assert entry["details"]["pii_redactions"] == 2
    assert ledger.verify_chain()


def test_overlong_correction_rejected():
    import pytest

    from banksupport.audit import AuditLedger
    from banksupport.feedback import MAX_CORRECTION_CHARS, FeedbackError, capture_feedback

    with pytest.raises(FeedbackError):
        capture_feedback(AuditLedger(), session_id="s", turn_id="t", rating="down",
                         correction="x" * (MAX_CORRECTION_CHARS + 1))
