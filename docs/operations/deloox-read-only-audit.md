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

## Recovery batch execution note

A guarded parser-error recovery batch completed successfully on 2026-10-27:
20 URLs were queued (10 each for Orioudh and PerfumeMarket). The post-apply
preview returned a disjoint next batch, so the verification correctly confirmed
that the just-applied URLs were no longer eligible. Continue only in separately
triggered, capped batches, checking queue outcomes between batches.
