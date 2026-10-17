# Bank Support Agents

A production-style **banking customer-support multi-agent system** built from
real enterprise design patterns: layered sub-agents over MCP-style tool
servers, tiered authentication and authorization, shared conversation memory,
confirmation guardrails, PII scrubbing, adversarial evals, and a
hash-chained audit ledger.

> **Synthetic data only.** All customers, accounts, transactions and balances
> are fictional and deterministic. No real banking systems are touched; no
> network access or API keys are required.

## The problem

A support chat that answers "what is my balance?" is easy. A support system
that is *safe to run* is hard: the same request from a standard-tier customer
("raise my credit limit") must be politely refused while a premium customer
gets it done; a card number pasted into chat must never reach a model; a
checkbook must never ship without the customer confirming the address; and
every confident-sounding number in an answer must actually come from a tool.

## Architecture (layers, in words)

```
User message
  -> Auth (token -> tier -> permissions)
  -> PII scrub (redact before anything model-like sees the text; seal originals)
  -> Memory (record turn; sub-agents share per-customer history)
  -> Orchestrator routes intents (multi-intent fans out)
       -> AccountsAgent   -> AccountsMCP      (balances, account info)
       -> TransactionsAgent -> TransactionsMCP (statements, flag suspicious)
       -> ServiceAgent    -> ServiceMCP        (checkbook, address, credit limit)
  -> Guardrails (dangerous actions held for explicit confirmation)
  -> Composed answer (every figure cited from tool output)
  -> Audit ledger (hash-chained: auth, tools, denials, redactions, confirmations)
```

Sub-agents discover capabilities from each MCP server's JSON tool manifest
and invoke tools through `call()` — they never touch core systems directly.

## The 8 design patterns implemented

1. **Layered agent build-up** — plain Q&A -> tool-using agents -> domain
   sub-agents -> orchestrated system (`agents.py`).
2. **MCP servers per domain** — accounts, transactions, service each behind
   their own tool server with a manifest (`mcp_servers.py`).
3. **Tiered authZ** — tool permissions per customer tier; denials are polite
   and never reveal other tiers' abilities (`auth.py`).
4. **Shared conversation state** — per-customer memory across sub-agents and
   sessions; "the transaction you flagged as suspicious last week" resolves
   (`memory.py`).
5. **PII scrub + sealed vault** — Luhn-validated card detection, SSN and
   account-number patterns redacted pre-model; originals sealed per session
   (`pii.py`).
6. **Confirmation guardrails** — checkbook/address/credit-limit actions are
   held until the customer confirms; large amounts always gate (`guardrails.py`).
7. **Adversarial evals** — number grounding, permission bypass, PII leak, and
   unconfirmed-action cases run against the real pipeline (`evals.py`).
8. **Hash-chained audit** — every auth decision, tool call, denial,
   redaction and confirmation is tamper-evident (`audit.py`).

## Quickstart

```python
from banksupport import build_system

system = build_system()
token = system.auth.login("CUST-1001")          # premium customer
print(system.respond(token, "What is my balance?"))
# According to our records, your savings account ending 4521 has a
# balance of $52,340.00; your checking account ending 7834 has a
# balance of $12,400.75.

print(system.respond(token, "get me my balance and my last 5 transactions"))

# Guardrailed flow:
print(system.respond(token, "please send me a checkbook"))
# ... confirm to proceed (action ID: act-0001).
print(system.confirm_action(token, "act-0001", approved=True))
# Done — checkbook request CHQ-0001 has been submitted ...
```

Run the tests and the adversarial evals:

```bash
python -m pytest -q
python -c "from banksupport import run_all_evals; \
           [print(r.name, r.passed, '-', r.reason) for r in run_all_evals()]"
```

## Production path

| Demo | Production |
|---|---|
| `FakeLLM` intent rules | Real model call (scrub-then-call contract unchanged) |
| In-process MCP servers | Real MCP servers (stdio/SSE) per domain |
| `AuthManager` tokens | Existing identity provider (OAuth2/OIDC), token-based |
| In-memory `PIIVault` | HSM-backed vault; self-hosted models for PII traffic |
| In-process ledger | Append-only store (WORM) with external anchoring |
| No network | WAF, rate limits, API gateway, DDoS protection at the edge |
| Deterministic fixtures | Core banking adapters behind the MCP servers |

See `docs/architecture.md` for Mermaid diagrams and the permission matrix.
