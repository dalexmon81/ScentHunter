# Controlled parser-error recovery

The production recovery is deliberately gated by the exact commit-message phrase
`trigger guarded parser error recovery`. The workflow waits for the same revision's
Fly deployment to succeed, runs a read-only dry run, then queues at most ten
eligible URLs per retailer. It only requeues active product URLs whose stored
failure signature matches a parser error fixed in current code; it does not
launch a full catalog resync or make retailer network requests from the recovery
script. A post-apply read-only check verifies that applied URLs no longer match
the recovery plan.

For ParfumZentrum, the recovery is restricted to the explicit URL allowlist and
requires HTTP 200 plus JSON-LD Product evidence. Other historical ParfumZentrum
errors are intentionally excluded.
