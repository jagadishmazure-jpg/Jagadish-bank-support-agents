"""Per-customer conversation memory shared across sub-agents.

Turns stateless tool calls into a support conversation: any sub-agent can
reference what happened earlier ("the transaction you flagged as
suspicious last week") because history and flags live here, keyed by
customer rather than by session.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List


class ConversationStore:
    def __init__(self) -> None:
        self._turns: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        # customer_id -> {txn_id: note}
        self._flags: Dict[str, Dict[str, str]] = defaultdict(dict)

    # -- turns ------------------------------------------------------------
    def add_turn(self, customer_id: str, role: str, text: str) -> None:
        self._turns[customer_id].append({"role": role, "text": text})

    def history(self, customer_id: str) -> List[Dict[str, str]]:
        return list(self._turns[customer_id])

    # -- suspicious-transaction flags --------------------------------------
    def flag_transaction(self, customer_id: str, txn_id: str, note: str = "") -> None:
        self._flags[customer_id][txn_id] = note

    def get_flags(self, customer_id: str) -> Dict[str, str]:
        return dict(self._flags[customer_id])

    # -- keyword recall -----------------------------------------------------
    def recall(self, customer_id: str, query: str, limit: int = 5) -> List[Dict[str, str]]:
        query_words = set(query.lower().split())
        scored = []
        for turn in self._turns[customer_id]:
            overlap = len(query_words & set(turn["text"].lower().split()))
            if overlap:
                scored.append((overlap, turn))
        scored.sort(key=lambda item: -item[0])
        return [turn for _, turn in scored[:limit]]
