# Isolated pilot launch request

This marker requests one guarded deployment of the isolated Offer Engine pilot
from `refactor/catalog-first-architecture`.

Target: `scenthunter-pilot-20261030`
Database: dedicated SQLite file on `scenthunter_pilot_data`
Production app and production volume are not targets.

This file is an execution marker only; it contains no credentials.

Retry after correcting Fly token newline handling.

Retry after replacing FLY_API_TOKEN with the new Fly Org Deploy Token.

Retry after Fly app was successfully created; tolerate formatted app list output.
