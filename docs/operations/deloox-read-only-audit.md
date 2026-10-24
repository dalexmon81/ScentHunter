# Deloox production read-only audit

The `Controlled Deloox queue recovery` workflow includes a read-only audit job. A commit to `main` whose message contains `diagnose Deloox recovery state` runs probes against these production endpoints:

- `/catalog-status` — catalog and discovery progress
- `/catalog/hydration-status` — persistent hydration queue states
- `/catalog/hydration-processing` — active processing leases
- `/diagnostic/runtime-deep` — runtime and thread diagnostics

This audit does not apply queue recovery or mutate production data. The guarded recovery job is separately gated by the exact phrase `trigger guarded Deloox recovery` and its parser-identity prechecks.
