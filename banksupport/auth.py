"""Token-based authentication with tiered authorization.

Tiers map to tool permissions: premium customers may use credit-limit
tools, standard customers may not. Denials are polite and never reveal
what other tiers can do.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Callable, Dict, Set, Tuple

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
    expires_at: float = float("inf")

    @property
    def permissions(self) -> Set[str]:
        return TIERS[self.tier]


class AuthManager:
    """Issues tokens and answers authorization questions.

    Tokens are opaque random strings (``secrets.token_urlsafe``, 256 bits) that
    carry no customer data, so they cannot be guessed or decoded. Each session
    expires after ``ttl_seconds``; ``clock`` is injectable for tests.
    """

    def __init__(self, ttl_seconds: float = 900.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._sessions: Dict[str, Session] = {}
        self.ttl_seconds = ttl_seconds
        self._clock = clock

    def login(self, customer_id: str) -> str:
        if customer_id not in mcp_servers.CUSTOMERS:
            raise AuthError(f"unknown customer '{customer_id}'")
        token = secrets.token_urlsafe(32)
        tier = mcp_servers.CUSTOMERS[customer_id]["tier"]
        self._sessions[token] = Session(token=token, customer_id=customer_id, tier=tier,
                                        expires_at=self._clock() + self.ttl_seconds)
        return token

    def logout(self, token: str) -> None:
        self._sessions.pop(token, None)

    def get_session(self, token: str) -> Session:
        session = self._sessions.get(token)
        if session is None:
            raise AuthError("invalid or expired token")
        if self._clock() >= session.expires_at:
            self._sessions.pop(token, None)
            raise AuthError("invalid or expired token")
        return session

    def authorize(self, token: str, permission: str) -> Tuple[bool, str]:
        """Return (allowed, reason). Denial reasons are customer-safe."""
        session = self.get_session(token)
        if permission in TIERS[session.tier]:
            return True, "allowed"
        return False, self.denial_message(permission)

    def denial_message(self, permission: str) -> str:
        return POLITE_DENIALS.get(permission, DEFAULT_DENIAL)
