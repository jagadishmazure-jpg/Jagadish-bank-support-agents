# Implementation guide: from offline build to Azure

> Status: **planned**. Nothing here has been deployed. The offline build in this
> repository is what exists today; this guide is how it would be taken to a
> real Azure environment.

## Azure service mapping

| Offline component | Azure service (planned) | Notes |
|---|---|---|
| Customer auth | Microsoft Entra External ID; the agent receives a validated token, not a password |  |
| Intent routing and answers | Azure OpenAI with tool calling | Keep figures from tool output only |
| Tool servers | MCP servers on Azure Container Apps behind API Management | Per-tool permission check stays in the server |
| PII | Azure AI Language PII detection plus the local validators |  |
| Audit | Append-only storage (immutable blob policy) or Azure Confidential Ledger |  |

## Steps

1. Replace keyword routing with a model that returns a tool call; keep the permission check in each tool.
2. Move sessions to a store with TTL (Redis) and tokens to Entra-issued ones.
3. Expose the three servers over real MCP and register them in API Management.
4. Run the four evals in CI against the model-backed version and add more from real failure cases.

## Guardrails to keep when going live

- Random session tokens with expiry and logout; the token reveals nothing about the customer.
- Tier permissions are checked inside the tool server, not only in the prompt.
- PII is redacted before routing and sealed per session.
- High-impact service actions need explicit confirmation by action id.
- Every tool call is written to a hash-chained audit log; `verify_chain()` detects edits.
- Feedback corrections are PII-scrubbed and capped at 2,000 characters before they reach the append-only ledger.

## What to measure before calling it production-ready

- Share of answers whose figures all match tool output (number grounding).
- Blocked permission-bypass attempts as a share of attempts.
- Pending actions confirmed, rejected or expired; time to confirmation.
