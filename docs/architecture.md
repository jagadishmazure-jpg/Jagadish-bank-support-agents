# Architecture

## Layered build-up

```mermaid
flowchart TB
    LLM["1. Plain LLM<br/>(no bank access)"]
    TOOL["2. Tool-using agent<br/>(balance via tools)"]
    SUB["3. Domain sub-agents<br/>(accounts / transactions / service)"]
    SYS["4. Orchestrated system<br/>(auth + memory + guardrails + audit)"]

    LLM --> TOOL --> SUB --> SYS
```

Each layer earns its complexity: tools ground answers, sub-agents own
domains, the orchestrator owns safety.

## Request flow

```mermaid
flowchart LR
    U["User message"] --> A["Auth<br/>token -> tier -> permissions"]
    A --> P["PII scrub<br/>redact; seal originals"]
    P --> M["Memory<br/>record turn"]
    M --> R["Orchestrator<br/>route intents"]
    R --> AA["AccountsAgent<br/>AccountsMCP"]
    R --> TA["TransactionsAgent<br/>TransactionsMCP"]
    R --> SA["ServiceAgent<br/>ServiceMCP"]
    AA --> G["Guardrails<br/>confirm dangerous actions"]
    TA --> G
    SA --> G
    G --> ANS["Composed answer<br/>figures cited from tools"]
    ANS --> AUD["Audit ledger<br/>hash-chained"]
```

Multi-intent messages ("balance and last 5 transactions") fan out to
multiple sub-agents; their answers are composed into one response.

## Tiered permission matrix

| Tool | Permission | Premium | Standard |
|---|---|---|---|
| list_accounts, get_balance, get_account_info | `accounts.read` | yes | yes |
| list_transactions, get_last_n | `transactions.read` | yes | yes |
| flag_suspicious | `transactions.flag` | yes | yes |
| request_checkbook | `service.checkbook` | yes (confirm) | yes (confirm) |
| update_address | `service.address` | yes (confirm) | yes (confirm) |
| increase_credit_limit | `service.credit_limit` | yes (confirm) | **denied** |

Denials are polite and tier-blind: a standard customer hears "I don't have
permission…", never "premium customers can".

## Confirmation gates

```mermaid
flowchart TB
    REQ["Action requested"] --> NEEDS{"needs_confirmation?"}
    NEEDS -->|checkbook / address / credit-limit<br/>or amount > $10,000| HOLD["HELD: ask customer to confirm<br/>(action ID issued)"]
    NEEDS -->|otherwise| EXEC["Execute via MCP tool"]
    HOLD --> C{"customer confirms?"}
    C -->|yes| PERM["re-check permission<br/>at execution time"]
    C -->|no| CANCEL["Cancelled: nothing submitted"]
    PERM --> EXEC2["Execute via MCP tool"]
```

## Trust boundary (PII)

```mermaid
flowchart LR
    RAW["Raw user text<br/>(may contain card numbers)"] --> SCRUB["PIIScrubber<br/>Luhn-validated redaction"]
    SCRUB --> VAULT[("PIIVault<br/>sealed per session")]
    SCRUB --> MODEL["Model / agents<br/>see only [REDACTED:*]"]
    VAULT -.->|"unseal inside<br/>trust boundary only"| TOOLS["MCP tools"]
```

## Audit ledger

Append-only entries: `message.received`, `pii.redacted`, `tool.called`,
`tool.denied`, `guardrail.held`, `guardrail.confirmed`,
`guardrail.executed`, `guardrail.cancelled`, `message.responded`.
Each entry hashes the previous entry's hash; `verify_chain()` detects
any tampering.
