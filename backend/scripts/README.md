# Backend operator scripts

Explicitly invoked maintenance and migration helpers. Diagnostic/debug scripts remain under the top-level tools/diagnostics and tools/debug directories.


## Retailer authorization records

`manage_store_authorization.py` is a local operator-only CLI. It is not exposed through FastAPI and must never be wrapped in an unauthenticated endpoint.

Before recording an approval:
1. Personally verify the retailer's written permission and retain the original evidence in an approved, access-controlled location.
2. Confirm the permission covers each requested scope, territory, data field, collection method, refresh cadence, attribution and any commercial restrictions.
3. Use the exact retailer/store slug and the exact authorization reference from the evidence.
4. Prefer a documented API/feed method. Do not infer permission from a public website, affiliate application, account registration or automated acknowledgement.

Mutations require a PostgreSQL connection and an explicit operator confirmation environment variable. Set it only for the individual command after verifying written consent:

```sh
export SCENTHUNTER_OPERATOR_CONFIRM=I_VERIFIED_WRITTEN_RETAILER_CONSENT
python backend/scripts/manage_store_authorization.py approve \
  --store exact-store-slug \
  --method feed \
  --scope product_discovery \
  --scope offer_data \
  --scope price_stock \
  --reference "retailer-ticket-or-contract-reference" \
  --evidence-url "https://approved-private-evidence-location.example/record" \
  --approved-by "operator identity" \
  --expires-at "2027-11-07T00:00:00Z" \
  --terms-json '{"territories":["LU"],"refresh_minutes":60}'
unset SCENTHUNTER_OPERATOR_CONFIRM
```

The example values above are placeholders, not permissions. Never run it with invented values. Omit scopes not explicitly granted. `price_stock` and `product_discovery` require `offer_data` as well.

Read existing records without mutation:

```sh
python backend/scripts/manage_store_authorization.py list
```

Revoke a grant without deleting its audit history:

```sh
export SCENTHUNTER_OPERATOR_CONFIRM=I_VERIFIED_WRITTEN_RETAILER_CONSENT
python backend/scripts/manage_store_authorization.py revoke \
  --store exact-store-slug \
  --authorization-id exact-grant-uuid \
  --notes "Permission withdrawn by retailer on YYYY-MM-DD"
unset SCENTHUNTER_OPERATOR_CONFIRM
```

Do not store credentials or the body of private correspondence in `terms` or `notes`. The evidence URL must be access-controlled; avoid public links to private retailer correspondence. CLI tests validate scope and timestamp rules without connecting to staging or production.
