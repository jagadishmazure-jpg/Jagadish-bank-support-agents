"""MCP-style tool servers for the banking support system.

Each server exposes a JSON tool manifest and a ``call()`` entrypoint,
mirroring the Model Context Protocol pattern: agents discover tools from
the manifest and invoke them through the server. Agents never touch core
banking systems directly.

All data is synthetic and fictional.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from itertools import count
from typing import Any, Dict, List, Optional, Tuple


class ToolError(Exception):
    """Base error for tool invocation failures."""


class UnknownTool(ToolError):
    """The requested tool is not in the server manifest."""


class PermissionDenied(ToolError):
    """The caller lacks the permission a tool requires."""


class AccountNotFound(ToolError):
    """No such account for this customer (also used to avoid leaking others)."""


@dataclass
class ToolDef:
    name: str
    description: str
    args_schema: Dict[str, str]
    required_permission: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Synthetic fixture data (fictional customers, accounts, transactions)
# ---------------------------------------------------------------------------
CUSTOMERS: Dict[str, Dict[str, Any]] = {
    "CUST-1001": {
        "name": "Aarav Sharma",
        "tier": "premium",
        "credit_limit": 500000.00,
        "registered_address": "221 Maple Avenue, Riverton, IL 60999",
    },
    "CUST-1002": {
        "name": "Priya Nair",
        "tier": "standard",
        "credit_limit": 150000.00,
        "registered_address": "14 Harbor Street, Bayview, CA 94999",
    },
}

ACCOUNTS: Dict[str, Dict[str, Any]] = {
    "SAV-4521": {"customer_id": "CUST-1001", "type": "savings", "balance": 52340.00},
    "CHK-7834": {"customer_id": "CUST-1001", "type": "checking", "balance": 12400.75},
    "SAV-9912": {"customer_id": "CUST-1002", "type": "savings", "balance": 18200.00},
}

TRANSACTIONS: Dict[str, List[Dict[str, Any]]] = {
    "SAV-4521": [
        {"id": "TXN-9001", "date": "2026-10-15", "description": "Brightcart online purchase",
         "amount": -200.00, "flagged": False},
        {"id": "TXN-9002", "date": "2026-10-14", "description": "Salary credit",
         "amount": 85000.00, "flagged": False},
        {"id": "TXN-9003", "date": "2026-10-12", "description": "Bank transfer to R. Mehta",
         "amount": -5000.00, "flagged": False},
        {"id": "TXN-9004", "date": "2026-10-10", "description": "Electricity bill",
         "amount": -2340.00, "flagged": False},
        {"id": "TXN-9005", "date": "2026-10-08", "description": "Interest credit",
         "amount": 412.50, "flagged": False},
        {"id": "TXN-9006", "date": "2026-10-05", "description": "ATM withdrawal",
         "amount": -10000.00, "flagged": False},
    ],
    "CHK-7834": [
        {"id": "TXN-9101", "date": "2026-10-13", "description": "Grocery store",
         "amount": -3250.00, "flagged": False},
        {"id": "TXN-9102", "date": "2026-10-11", "description": "Freelance payout",
         "amount": 22000.00, "flagged": False},
    ],
    "SAV-9912": [
        {"id": "TXN-9201", "date": "2026-10-14", "description": "Bookstore purchase",
         "amount": -850.00, "flagged": False},
        {"id": "TXN-9202", "date": "2026-10-09", "description": "Salary credit",
         "amount": 62000.00, "flagged": False},
    ],
}

_BASE_CUSTOMERS = copy.deepcopy(CUSTOMERS)
_BASE_ACCOUNTS = copy.deepcopy(ACCOUNTS)
_BASE_TRANSACTIONS = copy.deepcopy(TRANSACTIONS)


def reset_fixtures() -> None:
    """Restore synthetic fixtures in place (keeps existing references valid)."""
    CUSTOMERS.clear()
    CUSTOMERS.update(copy.deepcopy(_BASE_CUSTOMERS))
    ACCOUNTS.clear()
    ACCOUNTS.update(copy.deepcopy(_BASE_ACCOUNTS))
    TRANSACTIONS.clear()
    TRANSACTIONS.update(copy.deepcopy(_BASE_TRANSACTIONS))


def find_transaction(txn_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Internal lookup: (account_id, txn) or None. Not exposed as a tool."""
    for account_id, txns in TRANSACTIONS.items():
        for txn in txns:
            if txn["id"] == txn_id:
                return account_id, txn
    return None


class MCPServer:
    """Base class: manifest discovery + permission-checked dispatch."""

    server_name = "base"

    def tools(self) -> List[ToolDef]:
        return []

    def manifest(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self.tools()]

    def _resolve(self, tool_name: str, granted_permissions) -> ToolDef:
        for tool in self.tools():
            if tool.name == tool_name:
                if tool.required_permission not in granted_permissions:
                    raise PermissionDenied(
                        f"missing permission '{tool.required_permission}' "
                        f"for tool '{tool_name}'"
                    )
                return tool
        raise UnknownTool(f"{self.server_name}: unknown tool '{tool_name}'")

    def _owned_account(self, customer_id: str, account_id: str) -> Dict[str, Any]:
        acct = ACCOUNTS.get(account_id)
        if acct is None or acct["customer_id"] != customer_id:
            # Deliberately vague: never confirm other customers' accounts exist.
            raise AccountNotFound(f"account '{account_id}' not found")
        return acct

    def call(self, tool_name: str, args: Dict[str, Any],
             customer_id: str, granted_permissions) -> Dict[str, Any]:
        self._resolve(tool_name, granted_permissions)
        handler = getattr(self, "_tool_" + tool_name, None)
        if handler is None:
            raise UnknownTool(f"{self.server_name}: unknown tool '{tool_name}'")
        return handler(args, customer_id)


class AccountsMCP(MCPServer):
    server_name = "accounts"

    def tools(self) -> List[ToolDef]:
        return [
            ToolDef("list_accounts", "List the customer's accounts.",
                    {}, "accounts.read"),
            ToolDef("get_balance", "Get the current balance of an account.",
                    {"account_id": "string"}, "accounts.read"),
            ToolDef("get_account_info", "Get account type and holder details.",
                    {"account_id": "string"}, "accounts.read"),
        ]

    def _tool_list_accounts(self, args, customer_id):
        return [
            {"account_id": aid, "type": a["type"], "balance": a["balance"]}
            for aid, a in ACCOUNTS.items() if a["customer_id"] == customer_id
        ]

    def _tool_get_balance(self, args, customer_id):
        acct = self._owned_account(customer_id, args["account_id"])
        return {"account_id": args["account_id"], "balance": acct["balance"]}

    def _tool_get_account_info(self, args, customer_id):
        acct = self._owned_account(customer_id, args["account_id"])
        return {
            "account_id": args["account_id"],
            "type": acct["type"],
            "holder": CUSTOMERS[customer_id]["name"],
        }


class TransactionsMCP(MCPServer):
    server_name = "transactions"

    def tools(self) -> List[ToolDef]:
        return [
            ToolDef("list_transactions", "List transactions for an account.",
                    {"account_id": "string", "limit": "integer"}, "transactions.read"),
            ToolDef("get_last_n", "Get the last N transactions for an account.",
                    {"account_id": "string", "n": "integer"}, "transactions.read"),
            ToolDef("flag_suspicious", "Flag a transaction as suspicious.",
                    {"txn_id": "string", "note": "string"}, "transactions.flag"),
        ]

    def _tool_list_transactions(self, args, customer_id):
        acct = self._owned_account(customer_id, args["account_id"])
        limit = int(args.get("limit", 10))
        return TRANSACTIONS[args["account_id"]][:limit]

    def _tool_get_last_n(self, args, customer_id):
        self._owned_account(customer_id, args["account_id"])
        n = int(args.get("n", 5))
        return TRANSACTIONS[args["account_id"]][:n]

    def _tool_flag_suspicious(self, args, customer_id):
        found = find_transaction(args["txn_id"])
        if found is None:
            raise ToolError(f"transaction '{args['txn_id']}' not found")
        account_id, txn = found
        if ACCOUNTS[account_id]["customer_id"] != customer_id:
            raise ToolError(f"transaction '{args['txn_id']}' not found")
        txn["flagged"] = True
        txn["flag_note"] = args.get("note", "")
        return {"txn_id": txn["id"], "flagged": True}


class ServiceMCP(MCPServer):
    server_name = "service"

    def __init__(self):
        self._counter = count(1)

    def tools(self) -> List[ToolDef]:
        return [
            ToolDef("request_checkbook", "Request a checkbook for an account.",
                    {"account_id": "string", "delivery_address": "string"},
                    "service.checkbook"),
            ToolDef("update_address", "Update the customer's registered address.",
                    {"customer_id": "string", "new_address": "string"},
                    "service.address"),
            ToolDef("increase_credit_limit", "Increase the credit limit.",
                    {"customer_id": "string", "new_limit": "number"},
                    "service.credit_limit"),
        ]

    def _tool_request_checkbook(self, args, customer_id):
        self._owned_account(customer_id, args["account_id"])
        request_id = f"CHQ-{next(self._counter):04d}"
        return {
            "request_id": request_id,
            "account_id": args["account_id"],
            "delivery_address": args["delivery_address"],
            "status": "submitted",
        }

    def _tool_update_address(self, args, customer_id):
        if args["customer_id"] != customer_id:
            raise ToolError("cannot update another customer's address")
        CUSTOMERS[customer_id]["registered_address"] = args["new_address"]
        return {"customer_id": customer_id,
                "registered_address": args["new_address"]}

    def _tool_increase_credit_limit(self, args, customer_id):
        if args["customer_id"] != customer_id:
            raise ToolError("cannot change another customer's limit")
        new_limit = float(args["new_limit"])
        CUSTOMERS[customer_id]["credit_limit"] = new_limit
        return {"customer_id": customer_id, "credit_limit": new_limit}
