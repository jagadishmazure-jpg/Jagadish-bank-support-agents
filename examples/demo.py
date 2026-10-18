"""A premium and a standard customer through the guarded support pipeline."""
from banksupport import build_system, run_all_evals
from banksupport.audit import AuditLedger
from banksupport.feedback import capture_feedback, list_feedback

system = build_system()
premium = system.auth.login("CUST-1001")
standard = system.auth.login("CUST-1002")
print("token shape: opaque, length", len(premium), "| contains customer id:", "CUST" in premium)

print("\n> What is my balance?")
print(system.respond(premium, "What is my balance?"))
print("\n> get me my balance and my last 5 transactions")
print(system.respond(premium, "get me my balance and my last 5 transactions"))
print("\n> my card 4111 1111 1111 1111 was charged twice, flag the brightcart transaction as suspicious")
print(system.respond(premium, "my card 4111 1111 1111 1111 was charged twice, "
                              "flag the brightcart transaction as suspicious"))
print("\n> please send me a checkbook")
print(system.respond(premium, "please send me a checkbook"))
print(system.confirm_action(premium, "act-0001", approved=True))
print("\n[standard tier] > increase my credit limit to $40000")
print(system.respond(standard, "increase my credit limit to $40000"))

print("\nAdversarial evals:")
for r in run_all_evals():
    print(f"  {r.name}: {'PASS' if r.passed else 'FAIL'} - {r.reason}")
print("\naudit chain intact:", system.audit.verify_chain())

# Feedback capture: thumbs up/down into the same hash-chained ledger, PII scrubbed first.
ledger = AuditLedger()
capture_feedback(ledger, session_id="s-demo", turn_id="t1", rating="up")
fb = capture_feedback(ledger, session_id="s-demo", turn_id="t2", rating="down",
                      correction="balance was wrong for card 4111 1111 1111 1111")
print(f"Feedback: {len(list_feedback(ledger))} entries, stored correction {fb['details']['correction']!r}, "
      f"PII redactions {fb['details']['pii_redactions']}, chain verifies: {ledger.verify_chain()}")
