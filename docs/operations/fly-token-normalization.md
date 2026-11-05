# Fly.io API token normalization

The production Fly deployment workflow normalizes the repository secret at the point where each Fly CLI step receives it:

- Tokens beginning with `fm2_` are passed to `flyctl` with the `FlyV1 ` macaroon scheme prefix.
- Other token values are passed through unchanged.
- The secret is never printed or written to workflow logs.

This does not repair an expired, revoked, or insufficiently scoped token. If Fly still returns `unauthorized`, rotate `FLY_API_TOKEN` in GitHub Actions using a token authorized for the `scenthunter` app and its organization. Never paste the token into an issue, pull request, or chat.

The change is deliberately limited to workflow environment expressions. It does not change deployment triggers, Fly app configuration, volumes, machines, secrets, or database behavior.
