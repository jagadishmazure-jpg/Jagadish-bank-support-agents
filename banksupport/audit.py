"""Hash-chained audit ledger.

Every auth decision, tool call, denial, confirmation and PII redaction is
appended with a SHA-256 hash over the previous entry, so tampering with
history is detectable via verify_chain().
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional


class AuditLedger:
    def __init__(self) -> None:
        self.entries: List[Dict[str, Any]] = []

    def log(self, event: str, actor: str,
            details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        seq = len(self.entries)
        prev = self.entries[-1]["hash"] if self.entries else "GENESIS"
        payload = {
            "seq": seq,
            "ts": time.time(),
            "event": event,
            "actor": actor,
            "details": details or {},
            "prev_hash": prev,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        payload["hash"] = digest
        self.entries.append(payload)
        return payload

    def verify_chain(self) -> bool:
        prev = "GENESIS"
        for entry in self.entries:
            if entry["prev_hash"] != prev:
                return False
            body = {k: entry[k] for k in
                    ("seq", "ts", "event", "actor", "details", "prev_hash")}
            digest = hashlib.sha256(
                json.dumps(body, sort_keys=True).encode()
            ).hexdigest()
            if digest != entry["hash"]:
                return False
            prev = entry["hash"]
        return True
