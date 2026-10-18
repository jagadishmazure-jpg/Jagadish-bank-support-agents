# Interview points

Short, honest talking points for Jagadish-bank-support-agents. Every number quoted is from the
real run shown in the README.

- Permissions are enforced in the tool server, so a prompt injection cannot grant itself a tier.
- A finding from my own review: tokens were predictable; now `secrets.token_urlsafe(32)` with a TTL and logout, with tests.
- Number grounding eval: every amount in the answer must appear in a tool result.
- I can explain how this differs from the LangChain capstone: controls by hand vs the framework's middleware.

## Likely follow-up questions

- What if the model invents a balance? (The grounding eval fails; in production, a post-check blocks the reply.)
- Why seal PII instead of deleting it? (A tool may need the real value, e.g. to look up a card.)
- How would you handle an expired token mid-conversation? (Re-auth, keep memory keyed by customer, not token.)
