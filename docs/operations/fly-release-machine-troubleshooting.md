# Fly release-machine troubleshooting

For a failed Fly release command, retain the exact release-command machine ID from `flyctl deploy` output and collect its status and logs before changing runtime configuration.

The deploy workflow must not proceed to application rollout or worker verification when the release command fails. Confirm the production Alembic revision and queue table presence independently after a successful release command.

A release VM that exits abruptly is not evidence that an Alembic migration ran. Do not manually apply migrations or bypass the release command as a workaround.
