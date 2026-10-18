"""Tests for the banking customer-support multi-agent system.

All synthetic/fictional data. Deterministic: no network, no keys.
"""
import pytest

from banksupport import (
    AccountsMCP,
    AuthError,
    ConfirmationGate,
    ConversationStore,
    GuardrailError,
    PIIScrubber,
    PIIVault,
    ServiceMCP,
    TransactionsMCP,
    build_system,
    run_all_evals,
)
from banksupport.mcp_servers import (
    AccountNotFound,
    PermissionDenied,
    UnknownTool,
    find_transaction,
)


@pytest.fixture
def system():
    return build_system()


@pytest.fixture
def premium_token(system):
    return system.auth.login("CUST-1001")


@pytest.fixture
def standard_token(system):
    return system.auth.login("CUST-1002")


# ---------------------------------------------------------------------------
# MCP servers (5)
# ---------------------------------------------------------------------------
class TestMCP:
    def test_manifest_lists_tools_with_required_fields(self):
        for server in (AccountsMCP(), TransactionsMCP(), ServiceMCP()):
            manifest = server.manifest()
            assert manifest, f"{server.server_name} manifest empty"
            for tool in manifest:
                assert {"name", "description", "args_schema",
                        "required_permission"} <= set(tool)

    def test_unknown_tool_rejected(self):
        server = AccountsMCP()
        with pytest.raises(UnknownTool):
            server.call("delete_everything", {}, "CUST-1001", {"accounts.read"})

    def test_get_balance_returns_fixture_value(self):
        server = AccountsMCP()
        res = server.call("get_balance", {"account_id": "SAV-4521"},
                          "CUST-1001", {"accounts.read"})
        assert res["balance"] == 52340.00

    def test_account_ownership_enforced(self):
        server = AccountsMCP()
        with pytest.raises(AccountNotFound):
            server.call("get_balance", {"account_id": "SAV-4521"},
                        "CUST-1002", {"accounts.read"})

    def test_permission_enforced_at_server(self):
        server = ServiceMCP()
        with pytest.raises(PermissionDenied):
            server.call("increase_credit_limit",
                        {"customer_id": "CUST-1001", "new_limit": 1},
                        "CUST-1001", {"service.checkbook"})


# ---------------------------------------------------------------------------
# Agents (6)
# ---------------------------------------------------------------------------
class TestAgents:
    def test_balance_answer_cites_tool_number(self, system, premium_token):
        resp = system.respond(premium_token, "What is my account balance?")
        assert "$52,340.00" in resp
        assert "savings" in resp.lower()

    def test_multi_intent_composes_both_answers(self, system, premium_token):
        resp = system.respond(
            premium_token, "get me my balance along with the last five transactions")
        assert "$52,340.00" in resp
        assert "TXN-9001" in resp
        assert "Brightcart online purchase" in resp

    def test_unknown_intent_gets_clarification(self, system, premium_token):
        resp = system.respond(premium_token, "tell me a joke about banks")
        assert "balances" in resp.lower() or "transactions" in resp.lower()

    def test_flag_suspicious_flow(self, system, premium_token):
        resp = system.respond(
            premium_token, "please flag the brightcart transaction as suspicious")
        assert "TXN-9001" in resp
        found = find_transaction("TXN-9001")
        assert found is not None and found[1]["flagged"] is True

    def test_flagged_transaction_recalled_next_session(self, system, premium_token):
        system.respond(premium_token,
                       "please flag the brightcart transaction as suspicious")
        # "New session", same customer: memory is per-customer.
        token2 = system.auth.login("CUST-1001")
        resp = system.respond(
            token2, "was that the one I flagged as suspicious last week?")
        assert "TXN-9001" in resp

    def test_pii_never_reaches_response(self, system, premium_token):
        card = "4111111111111111"
        resp = system.respond(
            premium_token, f"my card is {card}, what is my balance?")
        assert card not in resp
        assert "$52,340.00" in resp


# ---------------------------------------------------------------------------
# Auth (6)
# ---------------------------------------------------------------------------
class TestAuth:
    def test_premium_may_increase_credit_limit(self, system, premium_token):
        allowed, _ = system.auth.authorize(premium_token, "service.credit_limit")
        assert allowed is True

    def test_standard_denied_credit_limit_politely(self, system, standard_token):
        resp = system.respond(standard_token,
                              "increase my credit limit to $40000")
        assert "permission" in resp.lower()
        assert "premium" not in resp.lower()  # never leaks tier abilities

    def test_bad_token_rejected(self, system):
        resp = system.respond("tok-bogus-0000", "what is my balance?")
        assert "invalid" in resp.lower()

    def test_login_returns_working_token(self, system):
        token = system.auth.login("CUST-1001")
        session = system.auth.get_session(token)
        assert session.customer_id == "CUST-1001"
        assert session.tier == "premium"

    def test_unknown_permission_denied(self, system, premium_token):
        allowed, _ = system.auth.authorize(premium_token, "vault.self_destruct")
        assert allowed is False

    def test_tokens_are_random_and_carry_no_customer_data(self, system):
        a = system.auth.login("CUST-1001")
        b = system.auth.login("CUST-1001")
        assert a != b
        assert len(a) >= 40
        assert "CUST" not in a and "1001" not in a

    def test_token_expires_after_ttl(self):
        from banksupport.auth import AuthManager
        now = [1000.0]
        auth = AuthManager(ttl_seconds=60, clock=lambda: now[0])
        token = auth.login("CUST-1001")
        assert auth.get_session(token).customer_id == "CUST-1001"
        now[0] += 61
        with pytest.raises(AuthError):
            auth.get_session(token)

    def test_logout_revokes_token(self, system):
        token = system.auth.login("CUST-1002")
        system.auth.logout(token)
        with pytest.raises(AuthError):
            system.auth.get_session(token)

    def test_unknown_customer_login_fails(self, system):
        with pytest.raises(AuthError):
            system.auth.login("CUST-9999")


# ---------------------------------------------------------------------------
# Memory (4)
# ---------------------------------------------------------------------------
class TestMemory:
    def test_add_and_recall_roundtrip(self):
        store = ConversationStore()
        store.add_turn("C-1", "user", "my card was charged twice for Streamly")
        hits = store.recall("C-1", "charged twice Streamly")
        assert len(hits) == 1
        assert hits[0]["role"] == "user"

    def test_recall_is_keyword_scored(self):
        store = ConversationStore()
        store.add_turn("C-1", "user", "what is my balance")
        store.add_turn("C-1", "user", "weather in Riverton today")
        hits = store.recall("C-1", "balance account")
        assert hits and "balance" in hits[0]["text"]

    def test_memory_isolated_per_customer(self):
        store = ConversationStore()
        store.add_turn("C-1", "user", "secret phrase alpha")
        assert store.recall("C-2", "secret phrase alpha") == []

    def test_flags_stored_and_retrieved(self):
        store = ConversationStore()
        store.flag_transaction("C-1", "TXN-1", "suspicious")
        assert store.get_flags("C-1") == {"TXN-1": "suspicious"}


# ---------------------------------------------------------------------------
# Guardrails (5)
# ---------------------------------------------------------------------------
class TestGuardrails:
    def _checkbook_action(self, system, token):
        system.respond(token, "please send me a checkbook")
        pending = system.guardrails.pending_for(token)
        assert len(pending) == 1
        return pending[0].action_id

    def test_checkbook_held_until_confirmed(self, system, premium_token):
        aid = self._checkbook_action(system, premium_token)
        action = system.guardrails.get(aid)
        assert action.status == "pending"
        assert not any(e["event"] == "guardrail.executed"
                       for e in system.audit.entries)

    def test_confirmed_checkbook_executes(self, system, premium_token):
        aid = self._checkbook_action(system, premium_token)
        resp = system.confirm_action(premium_token, aid, approved=True)
        assert "CHQ-" in resp
        assert system.guardrails.get(aid).status == "executed"

    def test_large_amount_needs_confirmation(self):
        assert ConfirmationGate.needs_confirmation("transfer", 15000.00) is True
        assert ConfirmationGate.needs_confirmation("transfer", 100.00) is False

    def test_rejected_confirmation_cancels(self, system, premium_token):
        aid = self._checkbook_action(system, premium_token)
        resp = system.confirm_action(premium_token, aid, approved=False)
        assert "cancelled" in resp.lower()
        assert system.guardrails.get(aid).status == "cancelled"

    def test_double_confirm_rejected(self, system, premium_token):
        aid = self._checkbook_action(system, premium_token)
        system.confirm_action(premium_token, aid, approved=True)
        with pytest.raises(GuardrailError):
            system.guardrails.confirm(aid, True)


# ---------------------------------------------------------------------------
# PII (5)
# ---------------------------------------------------------------------------
class TestPII:
    def test_valid_card_redacted(self):
        scrubber = PIIScrubber()
        out, redactions = scrubber.scrub("my card 4111111111111111 please")
        assert "4111111111111111" not in out
        assert "[REDACTED:CARD" in out
        assert redactions and redactions[0].pii_type == "CARD"

    def test_non_luhn_long_digits_redacted_as_account_number(self):
        scrubber = PIIScrubber()
        out, redactions = scrubber.scrub("ref 4111111111111112 done")
        assert "4111111111111112" not in out
        assert redactions and redactions[0].pii_type == "ACCOUNT_NUMBER"

    def test_ssn_redacted(self):
        scrubber = PIIScrubber()
        out, redactions = scrubber.scrub("ssn 123-45-6789 here")
        assert "123-45-6789" not in out
        assert any(r.pii_type == "SSN" for r in redactions)

    def test_clean_text_untouched(self):
        scrubber = PIIScrubber()
        out, redactions = scrubber.scrub("What is my account balance?")
        assert out == "What is my account balance?"
        assert redactions == []

    def test_vault_seal_unseal_roundtrip(self):
        vault = PIIVault()
        vault.seal("sess-1", {"[REDACTED:CARD:1]": "4111111111111111"})
        assert vault.unseal("sess-1", "[REDACTED:CARD:1]") == "4111111111111111"


# ---------------------------------------------------------------------------
# Evals (4)
# ---------------------------------------------------------------------------
class TestEvals:
    def test_number_grounding(self):
        (result,) = [r for r in run_all_evals() if r.name == "number_grounding"]
        assert result.passed, result.reason

    def test_permission_bypass(self):
        (result,) = [r for r in run_all_evals() if r.name == "permission_bypass"]
        assert result.passed, result.reason

    def test_pii_leak(self):
        (result,) = [r for r in run_all_evals() if r.name == "pii_leak"]
        assert result.passed, result.reason

    def test_unconfirmed_action(self):
        (result,) = [r for r in run_all_evals() if r.name == "unconfirmed_action"]
        assert result.passed, result.reason


# ---------------------------------------------------------------------------
# Audit (3)
# ---------------------------------------------------------------------------
class TestAudit:
    def test_chain_verifies_after_activity(self, system, premium_token):
        system.respond(premium_token, "What is my balance?")
        assert system.audit.verify_chain() is True
        assert len(system.audit.entries) > 0

    def test_tamper_detected(self, system, premium_token):
        system.respond(premium_token, "What is my balance?")
        system.audit.entries[0]["event"] = "forged.event"
        assert system.audit.verify_chain() is False

    def test_expected_event_types_logged(self, system, premium_token):
        system.respond(premium_token, "My card 4111111111111111, send checkbook")
        events = {e["event"] for e in system.audit.entries}
        assert {"message.received", "pii.redacted", "tool.called",
                "guardrail.held", "message.responded"} <= events
