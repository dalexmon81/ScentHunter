# Deloox production read-only audit

The `Controlled Deloox queue recovery` workflow includes a read-only audit job. A commit to `main` whose message contains `diagnose Deloox recovery state` runs probes against these production endpoints:

- `/catalog-status` — catalog and discovery progress
- `/catalog/hydration-status` — persistent hydration queue states
- `/catalog/hydration-processing` — active processing leases
- `/diagnostic/runtime-deep` — runtime and thread diagnostics

This audit does not apply queue recovery or mutate production data. The guarded recovery job is separately gated by the exact phrase `trigger guarded Deloox recovery` and its parser-identity prechecks.

## Bounded parser-error recovery

The separate `Controlled stale parser error recovery` workflow can be explicitly
triggered by a commit message containing `trigger guarded parser error recovery`.
It waits for the same revision's successful Fly deploy, runs a read-only dry-run,
then requeues only exact known parser-call failures, capped at ten URLs per store,
and verifies the applied URLs are no longer eligible. It does not run a bulk
catalog resync or perform network requests from the recovery script.

Do not use this trigger for generic HTTP failures, placeholder-price failures, or
unclassified parser errors. Review the dry-run allowlist and per-store counts first.
