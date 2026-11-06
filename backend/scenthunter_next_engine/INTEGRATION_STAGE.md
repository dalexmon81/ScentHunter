# Next Engine integration stage

This package is being introduced on top of the stable production baseline in a read-only, opt-in stage.

- The canonical read-only endpoint is `/catalog/search`; the normal frontend flow is `/search-start`.
- With rollout flags at their safe defaults, `/search-start` continues to use the legacy collector path. Shadow mode may compare catalog results but never serves them.
- The separate `/search` endpoint also remains a legacy collector endpoint; it must not be described as catalog-first.
- The normal frontend route is not yet switched to catalog-first. The master switch and an explicit canary percentage remain required, and a catalog failure is surfaced rather than silently falling back.
- Preview and shadow diagnostic routes require both `SCENTHUNTER_NEXT_ENABLED=1` and `SCENTHUNTER_NEXT_PREVIEW_ENABLED=1`.
- Do not enable production flags or switch the normal search route until staging has a populated PostgreSQL catalog, an authorized real offer has passed the end-to-end acceptance gate, and a controlled rollout is explicitly approved.
- This package is not yet a replacement adapter for normal search. A later change must compare identity and offer coverage against the existing implementation before cutover.


## Evidence-backed catalog learning

- Production shadow observations can produce a separate catalog proposal; they never write the source catalog directly.
- Variant proposals require matching product identity, explicit size, matching title/catalog concentration, and corroboration from at least two independent retailer domains.
- If a retailer URL explicitly identifies a different concentration than its displayed title, that observation is rejected.
- New product candidates and variant additions remain reviewable proposals and must pass CI before publication.
