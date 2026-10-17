"""Production-style banking customer-support multi-agent system.

Layered sub-agents (accounts / transactions / service) over MCP-style tool
servers, with tiered auth, conversation memory, confirmation guardrails,
PII scrubbing, adversarial evals and a hash-chained audit ledger.

All data is synthetic and fictional. Deterministic: no network, no keys.
"""

from .auth import AuthManager, AuthError, Session, TIERS
from .mcp_servers import (
    AccountsMCP,
    ServiceMCP,
    TransactionsMCP,
    reset_fixtures,
)
from .memory import ConversationStore
from .pii import PIIScrubber, PIIVault
from .guardrails import ConfirmationGate, GuardrailError
from .audit import AuditLedger
from .agents import SupportOrchestrator, build_system
from .evals import EvalResult, run_all_evals

__all__ = [
    "AuthManager",
    "AuthError",
    "Session",
    "TIERS",
    "AccountsMCP",
    "TransactionsMCP",
    "ServiceMCP",
    "reset_fixtures",
    "ConversationStore",
    "PIIScrubber",
    "PIIVault",
    "ConfirmationGate",
    "GuardrailError",
    "AuditLedger",
    "SupportOrchestrator",
    "build_system",
    "EvalResult",
    "run_all_evals",
]
