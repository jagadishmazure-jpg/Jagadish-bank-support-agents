"""Domain sub-agents and the support orchestrator.

A deterministic FakeLLM core stands in for a real model: intent ->
tool -> natural-language response with cited numbers. The scrub-then-
route-then-guard contract in SupportOrchestrator is the production
contract; swapping FakeLLM for a real model call keeps it intact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import mcp_servers
from .audit import AuditLedger
from .auth import AuthError, AuthManager, Session
from .guardrails import ConfirmationGate, GuardrailError
from .mcp_servers import (
    AccountsMCP,
    MCPServer,
    ServiceMCP,
    ToolError,
    TransactionsMCP,
    find_transaction,
    reset_fixtures,
)
from .memory import ConversationStore
from .pii import PIIScrubber, PIIVault


def _fmt(amount: float) -> str:
    return f"${amount:,.2f}"


@dataclass
class Ctx:
    """Everything a sub-agent needs for one turn."""
    auth: AuthManager
    session: Session
    accounts: AccountsMCP
    transactions: TransactionsMCP
    service: ServiceMCP
    memory: ConversationStore
    guardrails: ConfirmationGate
    vault: PIIVault
    audit: AuditLedger
    scrubbed_message: str = ""


class FakeLLM:
    """Deterministic stand-in for a model call: rule-based intent routing."""

    def classify(self, text: str) -> List[str]:
        t = text.lower()
        intents: List[str] = []
        if "balance" in t:
            intents.append("balance")
        if "transaction" in t or "statement" in t:
            intents.append("transactions")
        if "flag" in t and ("suspicious" in t or "fraud" in t):
            intents.append("flag_suspicious")
        if "checkbook" in t or "cheque book" in t or "chequebook" in t:
            intents.append("checkbook")
        if "address" in t:
            intents.append("address")
        if "credit limit" in t or ("credit" in t and "limit" in t):
            intents.append("credit_limit")
        return intents


def _authorized_call(ctx: Ctx, server: MCPServer, tool: str,
                     args: Dict, permission: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Authorize, then invoke. Returns (result, error_message)."""
    allowed, reason = ctx.auth.authorize(ctx.session.token, permission)
    if not allowed:
        ctx.audit.log("tool.denied", ctx.session.customer_id,
                      {"server": server.server_name, "tool": tool,
                       "permission": permission})
        return None, reason
    try:
        result = server.call(tool, args, ctx.session.customer_id, {permission})
    except ToolError as exc:
        return None, f"Sorry, I couldn't complete that: {exc}."
    ctx.audit.log("tool.called", ctx.session.customer_id,
                  {"server": server.server_name, "tool": tool, "args": args})
    return result, None


class SubAgent:
    name = "base"

    def handles(self, intent: str) -> bool:
        return False

    def handle(self, intent: str, ctx: Ctx) -> str:
        raise NotImplementedError


class AccountsAgent(SubAgent):
    name = "accounts"

    def handles(self, intent: str) -> bool:
        return intent == "balance"

    def handle(self, intent: str, ctx: Ctx) -> str:
        accts, err = _authorized_call(ctx, ctx.accounts, "list_accounts",
                                      {}, "accounts.read")
        if err:
            return err
        parts = []
        for acct in accts:
            last4 = acct["account_id"].split("-")[-1]
            parts.append(
                f"your {acct['type']} account ending {last4} has a balance "
                f"of {_fmt(acct['balance'])}"
            )
        return "According to our records, " + "; ".join(parts) + "."


class TransactionsAgent(SubAgent):
    name = "transactions"

    def handles(self, intent: str) -> bool:
        return intent in ("transactions", "flag_suspicious")

    def handle(self, intent: str, ctx: Ctx) -> str:
        if intent == "flag_suspicious":
            return self._flag(ctx)
        return self._list(ctx)

    def _accounts(self, ctx: Ctx):
        return _authorized_call(ctx, ctx.accounts, "list_accounts",
                                {}, "accounts.read")

    def _list(self, ctx: Ctx) -> str:
        accts, err = self._accounts(ctx)
        if err:
            return err
        match = re.search(r"last\s+(\d+)", ctx.scrubbed_message.lower())
        n = int(match.group(1)) if match else 5
        lines: List[str] = []
        for acct in accts:
            txns, err2 = _authorized_call(
                ctx, ctx.transactions, "get_last_n",
                {"account_id": acct["account_id"], "n": n}, "transactions.read")
            if err2:
                return err2
            for txn in txns:
                sign = "-" if txn["amount"] < 0 else "+"
                lines.append(
                    f"{txn['date']}: {txn['description']} ({txn['id']}) "
                    f"{sign}{_fmt(abs(txn['amount']))}"
                )
        if not lines:
            return "I couldn't find any recent transactions."
        return ("Here are your recent transactions:\n" +
                "\n".join(f"- {line}" for line in lines[:n]))

    def _flag(self, ctx: Ctx) -> str:
        t = ctx.scrubbed_message.lower()
        # Recall-style question ("was that the one I flagged...") -> memory.
        if any(q in t for q in ("was that", "which one", "did i", "have i", "?")):
            flags = ctx.memory.get_flags(ctx.session.customer_id)
            if not flags:
                return ("I don't have any record of a transaction being "
                        "flagged. Could you clarify which transaction you mean?")
            bits = []
            for txn_id in flags:
                found = find_transaction(txn_id)
                if found:
                    _, txn = found
                    bits.append(
                        f"{txn_id} ({txn['description']}, "
                        f"{_fmt(abs(txn['amount']))})"
                    )
                else:
                    bits.append(txn_id)
            return ("Yes — you flagged " + ", ".join(bits) +
                    " as suspicious. Our fraud team will review it.")
        # Otherwise this is a new flag request: find the transaction.
        accts, err = self._accounts(ctx)
        if err:
            return err
        stop = {"flag", "as", "suspicious", "the", "a", "please", "this",
                "that", "transaction", "mark"}
        words = set(re.findall(r"[a-z]+", t)) - stop
        target = None
        for acct in accts:
            txns, err2 = _authorized_call(
                ctx, ctx.transactions, "list_transactions",
                {"account_id": acct["account_id"], "limit": 50},
                "transactions.read")
            if err2:
                return err2
            for txn in txns:
                desc_words = set(re.findall(r"[a-z]+", txn["description"].lower()))
                if words & desc_words:
                    target = txn
                    break
            if target:
                break
        if target is None:
            return ("Which transaction would you like me to flag? Please "
                    "mention the merchant or the amount.")
        res, err3 = _authorized_call(
            ctx, ctx.transactions, "flag_suspicious",
            {"txn_id": target["id"]}, "transactions.flag")
        if err3:
            return err3
        ctx.memory.flag_transaction(
            ctx.session.customer_id, target["id"], "flagged as suspicious by customer")
        return (f"Done — I've flagged transaction {target['id']} "
                f"({target['description']}, {_fmt(abs(target['amount']))}) "
                f"as suspicious. Our fraud team will review it.")


class ServiceAgent(SubAgent):
    name = "service"

    def handles(self, intent: str) -> bool:
        return intent in ("checkbook", "address", "credit_limit")

    def handle(self, intent: str, ctx: Ctx) -> str:
        if intent == "checkbook":
            return self._checkbook(ctx)
        if intent == "address":
            return self._address(ctx)
        return self._credit_limit(ctx)

    def _customer_accounts(self, ctx: Ctx):
        return _authorized_call(ctx, ctx.accounts, "list_accounts",
                                {}, "accounts.read")

    def _checkbook(self, ctx: Ctx) -> str:
        allowed, reason = ctx.auth.authorize(ctx.session.token, "service.checkbook")
        if not allowed:
            ctx.audit.log("tool.denied", ctx.session.customer_id,
                          {"server": "service", "tool": "request_checkbook",
                           "permission": "service.checkbook"})
            return reason
        accts, err = self._customer_accounts(ctx)
        if err:
            return err
        account_id = accts[0]["account_id"]
        last4 = account_id.split("-")[-1]
        address = mcp_servers.CUSTOMERS[ctx.session.customer_id]["registered_address"]
        desc = (f"Checkbook request for account ending {last4}, "
                f"delivery to registered address")
        aid = ctx.guardrails.request(
            ctx.session.token, "checkbook", desc, server="service",
            tool="request_checkbook",
            tool_args={"account_id": account_id, "delivery_address": address},
            permission="service.checkbook")
        ctx.audit.log("guardrail.held", ctx.session.customer_id,
                      {"action_id": aid, "kind": "checkbook"})
        return (f"I've prepared a checkbook request for your account ending "
                f"{last4}, to be delivered to your registered address: "
                f"{address}. Please confirm to proceed "
                f"(action ID: {aid}).")

    def _address(self, ctx: Ctx) -> str:
        allowed, reason = ctx.auth.authorize(ctx.session.token, "service.address")
        if not allowed:
            ctx.audit.log("tool.denied", ctx.session.customer_id,
                          {"server": "service", "tool": "update_address",
                           "permission": "service.address"})
            return reason
        match = re.search(r"address to (.+)$", ctx.scrubbed_message.lower())
        if not match:
            return ("What is the new address? Please reply with the full "
                    "address, e.g. 'change my address to 45 Park Street, "
                    "Chennai 600001'.")
        new_address = match.group(1).strip().rstrip(".")
        aid = ctx.guardrails.request(
            ctx.session.token, "address_change",
            f"Update registered address to: {new_address}",
            server="service", tool="update_address",
            tool_args={"customer_id": ctx.session.customer_id,
                       "new_address": new_address},
            permission="service.address")
        ctx.audit.log("guardrail.held", ctx.session.customer_id,
                      {"action_id": aid, "kind": "address_change"})
        return ("Before I submit the address change, please confirm the new "
                f"delivery address: {new_address} (action ID: {aid}).")

    def _credit_limit(self, ctx: Ctx) -> str:
        allowed, reason = ctx.auth.authorize(ctx.session.token, "service.credit_limit")
        if not allowed:
            ctx.audit.log("tool.denied", ctx.session.customer_id,
                          {"server": "service", "tool": "increase_credit_limit",
                           "permission": "service.credit_limit"})
            return reason
        match = (re.search(r"\$\s?([\d,]+)", ctx.scrubbed_message)
                 or re.search(r"to\s+([\d,]+)", ctx.scrubbed_message.lower()))
        if not match:
            return ("What should the new credit limit be? Please reply with "
                    "an amount, e.g. 'increase my credit limit to $30000'.")
        new_limit = float(match.group(1).replace(",", ""))
        aid = ctx.guardrails.request(
            ctx.session.token, "credit_limit",
            f"Increase credit limit to {_fmt(new_limit)}",
            server="service", tool="increase_credit_limit",
            tool_args={"customer_id": ctx.session.customer_id,
                       "new_limit": new_limit},
            permission="service.credit_limit", amount=new_limit)
        ctx.audit.log("guardrail.held", ctx.session.customer_id,
                      {"action_id": aid, "kind": "credit_limit"})
        return (f"I've prepared a credit limit increase to {_fmt(new_limit)}. "
                f"Please confirm to proceed (action ID: {aid}).")


class SupportOrchestrator:
    """Routes scrubbed user messages to sub-agents and composes answers."""

    def __init__(self) -> None:
        reset_fixtures()
        self.auth = AuthManager()
        self.accounts = AccountsMCP()
        self.transactions = TransactionsMCP()
        self.service = ServiceMCP()
        self.memory = ConversationStore()
        self.guardrails = ConfirmationGate()
        self.vault = PIIVault()
        self.audit = AuditLedger()
        self.scrubber = PIIScrubber()
        self.llm = FakeLLM()
        self.agents: List[SubAgent] = [
            AccountsAgent(), TransactionsAgent(), ServiceAgent()
        ]
        self._servers: Dict[str, MCPServer] = {
            "accounts": self.accounts,
            "transactions": self.transactions,
            "service": self.service,
        }

    # -- main entrypoint -------------------------------------------------
    def respond(self, token: str, message: str) -> str:
        try:
            session = self.auth.get_session(token)
        except AuthError:
            return "Sorry, your session is invalid. Please log in again."
        self.audit.log("message.received", session.customer_id, {"token": token})

        # PII is scrubbed BEFORE anything model-like sees the message.
        scrubbed, redactions = self.scrubber.scrub(message)
        if redactions:
            self.vault.seal(token, {r.placeholder: r.original for r in redactions})
            self.audit.log("pii.redacted", session.customer_id,
                           {"types": sorted({r.pii_type for r in redactions})})
        self.memory.add_turn(session.customer_id, "user", scrubbed)

        intents = self.llm.classify(scrubbed)
        if "flag_suspicious" in intents and "transactions" in intents:
            intents.remove("transactions")

        ctx = Ctx(auth=self.auth, session=session, accounts=self.accounts,
                  transactions=self.transactions, service=self.service,
                  memory=self.memory, guardrails=self.guardrails,
                  vault=self.vault, audit=self.audit,
                  scrubbed_message=scrubbed)
        if not intents:
            resp = self._clarify()
        else:
            parts = []
            for intent in intents:
                agent = next((a for a in self.agents if a.handles(intent)), None)
                if agent is not None:
                    parts.append(agent.handle(intent, ctx))
            resp = "\n\n".join(parts) if parts else self._clarify()

        self.memory.add_turn(session.customer_id, "assistant", resp)
        self.audit.log("message.responded", session.customer_id, {})
        return resp

    def confirm_action(self, token: str, action_id: str,
                       approved: bool = True) -> str:
        """Execute (or cancel) a guardrail-held action."""
        try:
            session = self.auth.get_session(token)
        except AuthError:
            return "Sorry, your session is invalid. Please log in again."
        try:
            action = self.guardrails.confirm(action_id, approved)
        except GuardrailError as exc:
            return f"Sorry — {exc}."
        if not approved:
            self.audit.log("guardrail.cancelled", session.customer_id,
                           {"action_id": action_id})
            return "Understood — I've cancelled that request. Nothing was submitted."
        # Re-check permission at execution time: tiers may have changed.
        allowed, reason = self.auth.authorize(token, action.permission)
        if not allowed:
            self.audit.log("tool.denied", session.customer_id,
                           {"server": action.server, "tool": action.tool,
                            "permission": action.permission})
            return reason
        server = self._servers[action.server]
        try:
            result = server.call(action.tool, action.tool_args,
                                 session.customer_id, {action.permission})
        except ToolError as exc:
            return f"Sorry, I couldn't complete that: {exc}."
        self.guardrails.mark_executed(action_id)
        self.audit.log("guardrail.executed", session.customer_id,
                       {"action_id": action_id, "result": result})
        self.memory.add_turn(session.customer_id, "assistant",
                             f"Confirmed action {action_id} executed.")
        return self._execution_summary(action, result)

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _clarify() -> str:
        return ("I can help with account balances, recent transactions, "
                "flagging suspicious activity, checkbook requests, address "
                "updates, and credit limit requests. What would you like to do?")

    @staticmethod
    def _execution_summary(action, result: Dict) -> str:
        if action.tool == "request_checkbook":
            return (f"Done — checkbook request {result['request_id']} has been "
                    f"submitted for delivery to {result['delivery_address']}.")
        if action.tool == "update_address":
            return (f"Done — your registered address is now "
                    f"{result['registered_address']}.")
        if action.tool == "increase_credit_limit":
            return (f"Done — your credit limit has been increased to "
                    f"{_fmt(result['credit_limit'])}.")
        return f"Done — {action.tool} completed."


def build_system() -> SupportOrchestrator:
    """Fresh, isolated system (fixtures reset) — ideal for tests and evals."""
    return SupportOrchestrator()
