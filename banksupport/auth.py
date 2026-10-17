"""Token-based authentication with tiered authorization.

Tiers map to tool permissions: premium customers may use credit-limit
tools, standard customers may not. Denials are polite and never reveal
what other tiers can do.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from typing import Dict, Set, Tuple

from . import mcp_servers


class AuthError(Exception):
    """Bad token or unknown customer."""


# Tier -> granted tool permissions.
TIERS: Dict[str, Set[str]] = {
    "premium": {
        "accounts.read",
        "transactions.read",
        "transactions.flag",
        "service.checkbook",
        "service.address",
        "service.credit_limit",
    },
    "standard": {
        "accounts.read",
        "transactions.read",
        "transactions.flag",
        "service.checkbook",
        "service.address",
    },
}

POLITE_DENIALS = {
    "service.credit_limit": (
        "Sorry, I don't have permission to change credit limits on this "
        "account. Please contact your relationship manager and they will be "
        "happy to help."
    ),
}

DEFAULT_DENIAL = (
    "Sorry, I don't have permission to do that on this account. "
    "Please contact customer care for assistance."
)


@dataclass
class Session:
    token: str
    customer_id: str
    tier: str

    @property
    def permissions(self) -> Set[str]:
        return TIERS[self.tier]


class AuthManager:
    """Issues tokens and answers authorization questions."""

    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}
        self._counter = count(1)

    def login(self, customer_id: str) -> str:
        if customer_id not in mcp_servers.CUSTOMERS:
            raise AuthError(f"unknown customer '{customer_id}'")
        token = f"tok-{customer_id}-{next(self._counter):04d}"
        tier = mcp_servers.CUSTOMERS[customer_id]["tier"]
        self._sessions[token] = Session(token=token, customer_id=customer_id, tier=tier)
        return token

    def get_session(self, token: str) -> Session:
        try:
            return self._sessions[token]
        except KeyError:
            raise AuthError("invalid or expired token")

    def authorize(self, token: str, permission: str) -> Tuple[bool, str]:
        """Return (allowed, reason). Denial reasons are customer-safe."""
        session = self.get_session(token)
        if permission in TIERS[session.tier]:
            return True, "allowed"
        return False, self.denial_message(permission)

    def denial_message(self, permission: str) -> str:
        return POLITE_DENIALS.get(permission, DEFAULT_DENIAL)
