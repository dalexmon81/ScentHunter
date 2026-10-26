# Next Engine integration stage

This package is being introduced on top of the stable production baseline in a read-only, opt-in stage.

- Normal `/search` behavior remains the legacy catalog-first implementation.
- Preview and shadow diagnostic routes require both `SCENTHUNTER_NEXT_ENABLED=1` and `SCENTHUNTER_NEXT_PREVIEW_ENABLED=1`.
- Do not enable either production flag until the integration CI passes and a controlled production validation is approved.
- This package is not yet a replacement adapter for normal search. A later change must compare identity and offer coverage against the existing implementation before cutover.
