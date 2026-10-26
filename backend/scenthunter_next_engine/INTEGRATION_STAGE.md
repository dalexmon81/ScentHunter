# Next Engine integration stage

This package is being introduced on top of the stable production baseline in a read-only, opt-in stage.

- Normal `/search` behavior remains the legacy catalog-first implementation.
- Preview and shadow diagnostic routes require both `SCENTHUNTER_NEXT_ENABLED=1` and `SCENTHUNTER_NEXT_PREVIEW_ENABLED=1`.
- Do not enable either production flag until the integration CI passes and a controlled production validation is approved.
- This package is not yet a replacement adapter for normal search. A later change must compare identity and offer coverage against the existing implementation before cutover.


## Evidence-backed catalog learning

- Production shadow observations can produce a separate catalog proposal; they never write the source catalog directly.
- Variant proposals require matching product identity, explicit size, matching title/catalog concentration, and corroboration from at least two independent retailer domains.
- If a retailer URL explicitly identifies a different concentration than its displayed title, that observation is rejected.
- New product candidates and variant additions remain reviewable proposals and must pass CI before publication.
